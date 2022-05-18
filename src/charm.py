#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

from imp import reload
import logging
import os
import pwd
import shutil
import subprocess
from typing import Dict, List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase, RelationBrokenEvent, RelationChangedEvent, RelationCreatedEvent, RelationDepartedEvent, RelationJoinedEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

logger = logging.getLogger(__name__)

PGB = "pgbouncer"
PG_USER = "postgres"
PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
USERLIST_PATH = f"{PGB_DIR}/userlist.txt"
INSTANCE_PATH = f"{PGB_DIR}/instance_"

PG_RELATION = "postgres"
DB_KEY = "databases"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.framework.observe(self.on[PG_RELATION].relation_created, self._on_postgres_relation_created)
        self.framework.observe(self.on[PG_RELATION].relation_joined, self._on_postgres_relation_joined)
        self.framework.observe(self.on[PG_RELATION].relation_changed, self._on_postgres_relation_changed)
        self.framework.observe(self.on[PG_RELATION].relation_departed, self._on_postgres_relation_departed)
        self.framework.observe(self.on[PG_RELATION].relation_broken, self._on_postgres_relation_broken)

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
        os.mkdir(PGB_DIR, 0o777)
        os.chown(PGB_DIR, pg_user.pw_uid, pg_user.pw_gid)

        # Make a directory for each service to store logs, configs, pidfiles and sockets.
        # TODO this can be removed once socket activation is implemented (JIRA-218)
        for service_id in self.service_ids:
            os.mkdir(f"{INSTANCE_PATH}{service_id}", 0o777)
            os.chown(f"{INSTANCE_PATH}{service_id}", pg_user.pw_uid, pg_user.pw_gid)

        # Initialise pgbouncer.ini config files from defaults set in charm lib.
        ini = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        self._render_service_configs(ini)

        # Initialise userlist, generating passwords for initial users. All config files use the
        # same userlist, so we only need one.
        self._render_userlist(pgb.initialise_userlist_from_ini(ini))

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

            self.unit.status = ActiveStatus("pgbouncer started")
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
            self.unit.status = ActiveStatus()
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to get pgbouncer status")

    def _on_config_changed(self, _) -> None:
        """Config changed handler.

        Reads config values and parses them to pgbouncer config, restarting if necessary.
        """
        config = self._read_pgb_config()
        config["pgbouncer"]["pool_mode"] = self.config["pool_mode"]

        config.set_max_db_connection_derivatives(
            self.config["max_db_connections"],
            self._cores,
        )

        self._render_pgb_config(config, reload_pgbouncer=True)

    # ===================================
    #  Postgres relation hooks & helpers
    # ===================================

    def _on_postgres_relation_created(self, create_event: RelationCreatedEvent):
        """Handle relation-created event"""
        self._extract_dbs_from_relation(create_event)

    def _on_postgres_relation_joined(self, join_event: RelationJoinedEvent):
        """Handle relation-joined event"""
        self._extract_dbs_from_relation(join_event)

    def _on_postgres_relation_changed(self, change_event: RelationChangedEvent):
        """Handle relation-changed event"""
        self._extract_dbs_from_relation(change_event)

    def _on_postgres_relation_departed(self, depart_event: RelationDepartedEvent):
        """Handle relation-departed event"""
        # TODO block incoming transmissions
        # TODO ensure any final transmissions are sent
        pass

    def _on_postgres_relation_broken(self, broken_event: RelationBrokenEvent):
        """Handle relation-broken event"""
        # TODO block incoming transmissions
        # TODO ensure any final transmissions are sent
        pass

    def _extract_dbs_from_relation(self, event):
        """Extract database information from relation databag and write it to config"""
        cfg = self._read_pgb_config()
        dbs = event.relation.data[event.app][DB_KEY]
        cfg.add_dbs_to_config(dbs)
        # extract db information from relation databag
        # write it into config in an intelligent way
        self._render_pgb_config(cfg, reload_pgbouncer=True)


    # ==========================
    #  Generic Helper Functions
    # ==========================

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
        except apt.PackageNotFoundError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to install packages")

    # ==============================
    #  PgBouncer-Specific Utilities
    # ==============================

    def _read_pgb_config(self) -> pgb.PgbConfig:
        """Get config object from pgbouncer.ini file.

        Returns:
            PgbConfig object containing pgbouncer config.
        """
        with open(INI_PATH, "r") as file:
            config = pgb.PgbConfig(file.read())
        return config

    def _render_service_configs(self, primary_config: pgb.PgbConfig, reload_pgbouncer=False):
        """Derives config files for the number of required services from given config.

        This method takes a primary config and generates one unique config for each intended
        instance of pgbouncer, implemented as a templated systemd service.

        TODO JIRA-218: Once pgbouncer v1.14 is available, update to use socket activation:
        TODO https://warthogs.atlassian.net/browse/DPE-218
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")

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
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer application
                in the container. When config files are updated, pgbouncer must be restarted for
                the changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
            config_path: intended location for the config.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")
        self._render_file(config_path, pgbouncer_ini.render(), 0o777)

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
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer application
                in the container. When config files are updated, pgbouncer must be restarted for
                the changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer users")
        self._render_file(USERLIST_PATH, pgb.generate_userlist(userlist), 0o777)

        if reload_pgbouncer:
            self._reload_pgbouncer()

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

    def _render_file(self, path: str, content: str, mode: int) -> None:
        """Write content rendered from a template to a file.

        Args:
            path: the path to the file.
            content: the data to be written to the file.
            mode: access permission mask applied to the file using chmod (e.g. 0o640).
        """
        with open(path, "w+") as file:
            file.write(content)
        # Ensure correct permissions are set on the file.
        os.chmod(path, mode)
        # Get the uid/gid for the postgres user.
        u = pwd.getpwnam(PG_USER)
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)


if __name__ == "__main__":
    main(PgBouncerCharm)
