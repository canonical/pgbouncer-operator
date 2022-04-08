#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import logging
import os
import pwd
import subprocess
from typing import Dict, List

from charms.operator_libs_linux.v0 import apt, passwd
from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

logger = logging.getLogger(__name__)

PGB_DIR = "/etc/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
USERLIST_PATH = f"{PGB_DIR}/userlist.txt"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._pgbouncer_service = "pgbouncer"
        self._pgb_user = "pgbouncer"

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    # =======================
    #  Charm Lifecycle Hooks
    # =======================

    def _on_install(self, _) -> None:
        """On install hook.

        This initialises local config files necessary for pgbouncer to run.
        """
        self.unit.status = MaintenanceStatus("Installing and configuring PgBouncer")

        # Initialise prereqs to run pgbouncer
        self._install_apt_packages(["pgbouncer"])
        # create & add pgbouncer user to postgres group, which is created when installing
        # pgbouncer apt package
        passwd.add_user(
            username=self._pgb_user, password=pgb.generate_password(), primary_group="postgres"
        )
        user = pwd.getpwnam(self._pgb_user)
        self._postgres_gid = user.pw_gid
        self._pgbouncer_uid = user.pw_uid

        os.chown(PGB_DIR, self._pgbouncer_uid, self._postgres_gid)
        os.chown(INI_PATH, self._pgbouncer_uid, self._postgres_gid)
        os.chown(USERLIST_PATH, self._pgbouncer_uid, self._postgres_gid)
        os.setuid(self._pgbouncer_uid)

        # Initialise pgbouncer.ini config file from defaults in charm lib.
        ini = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        self._render_pgb_config(ini)

        # Initialise userlist, generating passwords for initial users
        self._render_userlist(pgb.initialise_userlist_from_ini(ini))

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def _on_start(self, _) -> None:
        """On Start hook.

        Switches to pgbouncer user and runs pgbouncer as daemon
        """
        try:
            # -d flag ensures pgbouncer runs as a daemon, not as an active process.
            command = ["pgbouncer", "-d", INI_PATH]
            logger.debug(f"pgbouncer call: {' '.join(command)}")
            # Ensure pgbouncer command runs as pgbouncer user.
            self._pgbouncer_uid = pwd.getpwnam(self._pgb_user).pw_uid
            os.setuid(self._pgbouncer_uid)
            subprocess.check_call(command)
            self.unit.status = ActiveStatus("pgbouncer started")
        except subprocess.CalledProcessError as e:
            logger.info(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")

    def _on_config_changed(self, _) -> None:
        """Config changed handler.

        Reads config values and parses them to pgbouncer config, restarting if necessary.
        """
        config = self._read_pgb_config()
        config["pgbouncer"]["pool_mode"] = self.config["pool_mode"]
        config.set_max_db_connection_derivatives(
            self.config["max_db_connections"],
            os.cpu_count(),
        )
        logger.info(dict(config))
        self._render_pgb_config(config, reload_pgbouncer=True)

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
        # Get the uid/gid for the pgbouncer user.
        u = pwd.getpwnam(self._pgb_user)
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)

    def _read_file(self, path: str) -> str:
        """Get content from file.

        Args:
            path: path to file
        Returns:
            string containing file content.
        """
        with open(path, "r") as f:
            file = f.read()
        return file

    # =====================================
    #  PgBouncer-Specific Helper Functions
    # =====================================

    def _read_pgb_config(self) -> pgb.PgbConfig:
        """Get config object from pgbouncer.ini file.

        Returns:
            PgbConfig object containing pgbouncer config.
        """
        return pgb.PgbConfig(self._read_file(INI_PATH))

    def _render_pgb_config(
        self, pgbouncer_ini: pgb.PgbConfig, reload_pgbouncer: bool = False
    ) -> None:
        """Render config object to pgbouncer.ini file.

        Args:
            pgbouncer_ini: PgbConfig object containing pgbouncer config.
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer application
                in the container. When config files are updated, pgbouncer must be restarted for
                the changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")
        self._render_file(INI_PATH, pgbouncer_ini.render(), 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _read_userlist(self) -> Dict[str, str]:
        return pgb.parse_userlist(self._read_file(USERLIST_PATH))

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
        self._render_file(USERLIST_PATH, pgb.generate_userlist(userlist), 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _reload_pgbouncer(self):
        self.unit.status = MaintenanceStatus("Restarting PgBouncer")
        # Restart pgbouncer here
        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(PgBouncerCharm)
