#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import logging
import os
import pwd
import shutil
import subprocess
from copy import deepcopy
from typing import Dict, List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_operator.v0 import pgb
from charms.pgbouncer_operator.v0.pgb import PgbConfig
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from constants import BACKEND_DB_ADMIN, INI_PATH
from constants import PG as PG_USER
from constants import PGB, PGB_DIR, USERLIST_PATH
from relations.backend_db_admin import BackendDbAdminRequires
from relations.db import DbProvides

logger = logging.getLogger(__name__)

INSTANCE_PATH = f"{PGB_DIR}/instance_"
PEER = "pgbouncer-replicas"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.legacy_db_relation = DbProvides(self, admin=False)
        self.legacy_db_admin_relation = DbProvides(self, admin=True)
        self.legacy_backend_relation = BackendDbAdminRequires(self)

        self._cores = os.cpu_count()
        self.service_ids = [service_id for service_id in range(self._cores)]
        self.pgb_services = [f"{PGB}@{service_id}" for service_id in self.service_ids]

    # =======================
    #  Charm Lifecycle Hooks
    # =======================

    def _on_install(self, _) -> None:
        """On install hook.

        This initialises local config files necessary for pgbouncer to run.
        """
        self.unit.status = MaintenanceStatus("Installing and configuring PgBouncer")

        self._install_apt_packages([PGB])

        pg_user = pwd.getpwnam(PG_USER)
        os.mkdir(PGB_DIR, 0o700)
        os.chown(PGB_DIR, pg_user.pw_uid, pg_user.pw_gid)

        # Make a directory for each service to store logs, configs, pidfiles and sockets.
        # TODO this can be removed once socket activation is implemented (JIRA-218)
        for service_id in self.service_ids:
            os.mkdir(f"{INSTANCE_PATH}{service_id}", 0o700)
            os.chown(f"{INSTANCE_PATH}{service_id}", pg_user.pw_uid, pg_user.pw_gid)

        # Initialise pgbouncer.ini config files from defaults set in charm lib and current config
        cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        self._render_service_configs(cfg)

        # Initialise userlist, generating passwords for initial users. All config files use the
        # same userlist, so we only need one.
        self._render_userlist(pgb.initialise_userlist_from_ini(cfg))

        # Copy pgbouncer service file and reload systemd
        shutil.copy("src/pgbouncer@.service", "/etc/systemd/system/pgbouncer@.service")
        systemd.daemon_reload()
        # Apt package starts its own pgbouncer service. Disable this so we can start and control
        # our own.
        systemd.service_stop(PGB)

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def _on_start(self, _) -> None:
        """On Start hook.

        Runs pgbouncer through systemd (configured in src/pgbouncer.service)
        """
        try:
            for service in self.pgb_services:
                logger.info(f"starting {service}")
                systemd.service_start(f"{service}")

            if self._has_backend_relation():
                self.unit.status = ActiveStatus("pgbouncer started")
            else:
                # Wait for backend relation relation if it doesn't exist
                self.unit.status = BlockedStatus("waiting for backend database relation")
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")

    def _on_update_status(self, _) -> None:
        """Update Status hook.

        Uses systemd status to verify pgbouncer is running.
        """
        try:
            for service in self.pgb_services:
                if not systemd.service_running(f"{service}"):
                    self.unit.status = self.unit.status = BlockedStatus(
                        f"{service} is not running - try restarting using `juju actions pgbouncer restart`"
                    )
                    return

            if self._has_backend_relation():
                # All is well, set ActiveStatus
                self.unit.status = ActiveStatus()
            else:
                # If we don't have any backend, this charm doesn't serve a purpose, and therefore
                # should be related to one or removed.
                self.unit.status = BlockedStatus("waiting for backend database relation")
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to get pgbouncer status")

    def _on_config_changed(self, _) -> None:
        """Config changed handler.

        Reads charm config values, generates derivative values, writes new pgbouncer config, and
        restarts pgbouncer to apply changes.
        """
        cfg = self.read_pgb_config()
        cfg["pgbouncer"]["pool_mode"] = self.config["pool_mode"]

        cfg.set_max_db_connection_derivatives(
            self.config["max_db_connections"],
            self._cores,
        )

        cfg["pgbouncer"]["listen_addr"] = str(self.unit_ip)

        self._render_service_configs(cfg, reload_pgbouncer=True)

    # ==============================
    #  PgBouncer-Specific Utilities
    # ==============================

    def read_pgb_config(self) -> pgb.PgbConfig:
        """Get config object from pgbouncer.ini file.

        Returns:
            PgbConfig object containing pgbouncer config.
        """
        with open(INI_PATH, "r") as file:
            config = pgb.PgbConfig(file.read())
        return config

    def _render_service_configs(self, config: pgb.PgbConfig, reload_pgbouncer=False):
        """Derives config files for the number of required services from given config.

        This method takes a primary config and generates one unique config for each intended
        instance of pgbouncer, implemented as a templated systemd service.

        TODO JIRA-218: Once pgbouncer v1.14 is available, update to use socket activation:
             https://warthogs.atlassian.net/browse/DPE-218. This is available in Ubuntu 22.04, but
             not 20.04.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")

        # create a copy of the config so the original reference is unchanged.
        primary_config = deepcopy(config)

        # Render primary config. This config is the only copy that the charm reads from to create
        # PgbConfig objects, and is modified below to implement individual services.
        self._render_pgb_config(pgb.PgbConfig(primary_config), config_path=INI_PATH)

        # Modify & render config files for each service instance
        for service_id in self.service_ids:
            instance_dir = f"{INSTANCE_PATH}{service_id}"  # Generated in on_install hook

            primary_config[PGB]["unix_socket_dir"] = instance_dir
            primary_config[PGB]["logfile"] = f"{instance_dir}/pgbouncer.log"
            primary_config[PGB]["pidfile"] = f"{instance_dir}/pgbouncer.pid"

            self._render_pgb_config(primary_config, config_path=f"{instance_dir}/pgbouncer.ini")

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _render_pgb_config(
        self,
        pgbouncer_ini: pgb.PgbConfig,
        reload_pgbouncer: bool = False,
        config_path: str = INI_PATH,
    ) -> None:
        """Render config object to pgbouncer.ini file.

        Args:
            pgbouncer_ini: PgbConfig object containing pgbouncer config.
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
            config_path: intended location for the config.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")
        self.render_file(config_path, pgbouncer_ini.render(), 0o700)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _read_userlist(self) -> Dict[str, str]:
        with open(USERLIST_PATH, "r") as file:
            userlist = pgb.parse_userlist(file.read())
        return userlist

    def _render_userlist(self, userlist: Dict[str, str], reload_pgbouncer: bool = False):
        """Render user list (with encoded passwords) to pgbouncer.ini file.

        Args:
            userlist: dictionary of users:password strings.
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer users")
        self.render_file(USERLIST_PATH, pgb.generate_userlist(userlist), 0o700)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def add_user(
        self,
        user: str,
        password: str = None,
        admin: bool = False,
        stats: bool = False,
        cfg: PgbConfig = None,
        reload_pgbouncer: bool = False,
        render_cfg: bool = False,
    ):
        """Adds a user to the config files.

        Args:
            user: the username for the intended user
            password: intended password for the user
            admin: whether or not the user has admin permissions
            stats: whether or not the user has stats permissions
            cfg: A pgb.PgbConfig object that can be used to minimise writes and restarts. Modified
                during this method.
            reload_pgbouncer: whether or not to restart pgbouncer after changing config. Must be
                restarted for changes to take effect.
            render_cfg: whether or not to render config
        """
        if not cfg:
            cfg = self.read_pgb_config()
        userlist = self._read_userlist()

        # Userlist is key-value dict of users and passwords.
        if not password:
            password = pgb.generate_password()

        # Return early if user and password are already set to the correct values
        if userlist.get(user) == password:
            return

        userlist[user] = password

        if admin and user not in cfg[PGB]["admin_users"]:
            cfg[PGB]["admin_users"].append(user)
        if stats and user not in cfg[PGB]["stats_users"]:
            cfg[PGB]["stats_users"].append(user)

        self._render_userlist(userlist)
        if render_cfg:
            self._render_service_configs(cfg, reload_pgbouncer)

    def remove_user(
        self,
        user: str,
        cfg: PgbConfig = None,
        reload_pgbouncer: bool = False,
        render_cfg: bool = False,
    ):
        """Removes a user from config files.

        Args:
            user: the username for the intended user.
            cfg: A pgb.PgbConfig object that can be used to minimise writes and restarts. Modified
                during this method.
            reload_pgbouncer: whether or not to restart pgbouncer after changing config. Must be
                restarted for changes to take effect.
            render_cfg: whether or not to render config
        """
        if not cfg:
            cfg = self.read_pgb_config()
        userlist = self._read_userlist()

        if user not in userlist.keys():
            return

        # remove userlist
        del userlist[user]

        if user in cfg[PGB]["admin_users"]:
            cfg[PGB]["admin_users"].remove(user)
        if user in cfg[PGB]["stats_users"]:
            cfg[PGB]["stats_users"].remove(user)

        self._render_userlist(userlist)
        if render_cfg:
            self._render_service_configs(cfg, reload_pgbouncer)

    def _reload_pgbouncer(self):
        """Reloads systemd pgbouncer service."""
        self.unit.status = MaintenanceStatus("Reloading Pgbouncer")
        try:
            for service in self.pgb_services:
                systemd.service_reload(service, restart_on_failure=True)
            self.unit.status = ActiveStatus("PgBouncer Reloaded")
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("Failed to restart pgbouncer")

    # =================
    #  Charm Utilities
    # =================

    def _install_apt_packages(self, packages: List[str]):
        """Simple wrapper around 'apt-get install -y."""
        try:
            logger.debug("updating apt cache")
            apt.update()
        except subprocess.CalledProcessError as e:
            logger.exception("failed to update apt cache, CalledProcessError", exc_info=e)
            self.unit.status = BlockedStatus("failed to update apt cache")
            return

        try:
            logger.debug(f"installing apt packages: {', '.join(packages)}")
            apt.add_package(packages)
        except (apt.PackageNotFoundError, apt.PackageError, TypeError) as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to install packages")

    def render_file(self, path: str, content: str, mode: int) -> None:
        """Write content rendered from a template to a file.

        Args:
            path: the path to the file.
            content: the data to be written to the file.
            mode: access permission mask applied to the file using chmod (e.g. 0o700).
        """
        with open(path, "w+") as file:
            file.write(content)
        # Ensure correct permissions are set on the file.
        os.chmod(path, mode)
        # Get the uid/gid for the postgres user.
        u = pwd.getpwnam(PG_USER)
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)

    def _has_backend_relation(self) -> bool:
        """Returns whether or not this charm is related to a postgresql backend.

        TODO this will be updated to include the new backend relation once it is written.
        """
        legacy_backend_relation = self.model.get_relation(BACKEND_DB_ADMIN)
        return legacy_backend_relation is not None

    @property
    def unit_ip(self) -> str:
        """Current unit IP."""
        return self.model.get_binding(PEER).network.bind_address


if __name__ == "__main__":
    main(PgBouncerCharm)
