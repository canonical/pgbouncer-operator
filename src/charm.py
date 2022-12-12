#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import logging
import os
import pwd
import shutil
import subprocess
from typing import List, Optional, Union

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_k8s.v0 import pgb
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from constants import AUTH_FILE_PATH, CLIENT_RELATION_NAME, INI_PATH, PEERS
from constants import PG as PG_USER
from constants import PGB, PGB_DIR
from relations.backend_database import BackendDatabaseRequires
from relations.db import DbProvides
from relations.peers import Peers
from relations.pgbouncer_provider import PgBouncerProvider

logger = logging.getLogger(__name__)

INSTANCE_PATH = f"{PGB_DIR}/instance_"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.peers = Peers(self)
        self.backend = BackendDatabaseRequires(self)
        self.client_relation = PgBouncerProvider(self)
        self.legacy_db_relation = DbProvides(self, admin=False)
        self.legacy_db_admin_relation = DbProvides(self, admin=True)

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

        # Initialise pgbouncer.ini config files from defaults set in charm lib and current config.
        # We'll add basic configs for now even if this unit isn't a leader, so systemd doesn't
        # throw a fit.
        cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        self.render_pgb_config(cfg)

        # Copy pgbouncer service & socket systemd files, and reload systemd
        shutil.copy("src/pgbouncer@.service", "/etc/systemd/system/pgbouncer@.service")
        self.update_systemd_socket()

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

            if self.backend.postgres:
                self.unit.status = ActiveStatus("pgbouncer started")
            else:
                # Wait for backend relation relation if it doesn't exist
                self.unit.status = BlockedStatus("waiting for backend database relation")
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")

    def _on_leader_elected(self, _):
        self.peers.update_connection()

    def _on_update_status(self, _) -> None:
        """Update Status hook."""
        self.unit.status = self.check_status()

    def _on_config_changed(self, _) -> None:
        """Config changed handler.

        Reads charm config values, generates derivative values, writes new pgbouncer config, and
        restarts pgbouncer to apply changes.
        """
        if not self.unit.is_leader():
            return

        cfg = self.read_pgb_config()
        cfg["pgbouncer"]["pool_mode"] = self.config["pool_mode"]

        cfg.set_max_db_connection_derivatives(
            self.config["max_db_connections"],
            self._cores,
        )

        if cfg["pgbouncer"]["listen_port"] != self.config["listen_port"]:
            self.update_client_connection_info(self.config["listen_port"])
            cfg["pgbouncer"]["listen_port"] = self.config["listen_port"]
            self.update_systemd_socket()

        self.render_pgb_config(cfg, reload_pgbouncer=True)

    def check_status(self) -> Union[ActiveStatus, BlockedStatus, WaitingStatus]:
        """Checks status of PgBouncer application.

        Checks whether pgb config is available, backend is ready, and pgbouncer systemd service is
        running.

        Returns:
            Recommended unit status. Can be active, blocked, or waiting.
        """
        try:
            self.read_pgb_config()
        except FileNotFoundError:
            wait_str = "waiting for pgbouncer to start"
            logger.warning(wait_str)
            return WaitingStatus(wait_str)
        try:
            for service in self.pgb_services:
                if not systemd.service_running(f"{service}"):
                    return BlockedStatus(f"{service} is not running")
        except systemd.SystemdError as e:
            logger.error(e)
            return BlockedStatus("failed to get pgbouncer status")

        if not self.backend.ready:
            # We can't relate an app to the backend database without a backend postgres relation
            backend_wait_msg = "waiting for backend database relation to connect"
            logger.warning(backend_wait_msg)
            return BlockedStatus(backend_wait_msg)

        return ActiveStatus()

    def reload_pgbouncer(self):
        """Restarts systemd pgbouncer service."""
        self.unit.status = MaintenanceStatus("Reloading Pgbouncer")
        try:
            for service in self.pgb_services:
                systemd.service_restart(service)
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("Failed to restart pgbouncer")

        self.unit.status = self.check_status()

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

    def render_pgb_config(self, config: pgb.PgbConfig, reload_pgbouncer=False):
        """Renders PGB config object to pgbouncer.ini file.

        Args:
            config: PgbConfig object containing pgbouncer config.
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")
        self.peers.update_cfg(config)
        self.render_file(INI_PATH, config.render(), 0o700)
        if reload_pgbouncer:
            self.reload_pgbouncer()

    def render_auth_file(self, auth_file: str, reload_pgbouncer: bool = False):
        """Render user list (with encoded passwords) to pgbouncer.ini file.

        Args:
            auth_file: the auth file to be rendered
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer users")

        self.peers.update_auth_file(auth_file)
        self.render_file(AUTH_FILE_PATH, auth_file, perms=0o700)

        if reload_pgbouncer:
            self.reload_pgbouncer()

    def update_systemd_socket(self):
        """Updates pgbouncer systemd socket, and reloads systemd."""
        with open("src/pgbouncer@.socket", "r") as file:
            socket_cfg = file.read()
        socket_cfg = socket_cfg.replace("PORT_PLACEHOLDER", str(self.config["listen_port"]))
        self.render_file("/etc/systemd/system/pgbouncer@.socket", socket_cfg, perms=0o664)
        systemd.daemon_reload()

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

    def render_file(self, path: str, content: str, perms: int) -> None:
        """Write content rendered from a template to a file.

        Args:
            path: the path to the file.
            content: the data to be written to the file.
            perms: access permission mask applied to the file using chmod (e.g. 0o700).
        """
        with open(path, "w+") as file:
            file.write(content)
        # Ensure correct permissions are set on the file.
        os.chmod(path, perms)
        # Get the uid/gid for the postgres user.
        u = pwd.getpwnam(PG_USER)
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)

    def delete_file(self, path: str):
        """Deletes file at the given path."""
        if os.path.exists(path):
            os.remove(path)

    @property
    def unit_ip(self) -> str:
        """Current unit IP."""
        return str(self.model.get_binding(PEERS).network.bind_address)

    # =====================
    #  Relation Utilities
    # =====================

    def update_client_connection_info(self, port: Optional[str] = None):
        """Update ports in backend relations to match updated pgbouncer port."""
        # Skip updates if backend.postgres doesn't exist yet.
        if not self.backend.postgres:
            return

        if port is None:
            port = self.config["listen_port"]

        for relation in self.model.relations.get("db", []):
            self.legacy_db_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get("db-admin", []):
            self.legacy_db_admin_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            self.client_relation.update_connection_info(relation)

    def update_postgres_endpoints(self, reload_pgbouncer):
        """Update postgres endpoints in relation config values."""
        # Skip updates if backend.postgres doesn't exist yet.
        if not self.backend.postgres or not self.unit.is_leader():
            return

        self.unit.status = MaintenanceStatus("Model changed - updating postgres endpoints")

        for relation in self.model.relations.get("db", []):
            self.legacy_db_relation.update_postgres_endpoints(relation, reload_pgbouncer=False)

        for relation in self.model.relations.get("db-admin", []):
            self.legacy_db_admin_relation.update_postgres_endpoints(
                relation, reload_pgbouncer=False
            )

        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            self.client_relation.update_postgres_endpoints(relation, reload_pgbouncer=False)

        if reload_pgbouncer:
            self.reload_pgbouncer()

    @property
    def leader_ip(self) -> str:
        """Gets leader ip."""
        return self.peers.leader_ip


if __name__ == "__main__":
    main(PgBouncerCharm)
