#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import logging
import os
import pwd
import subprocess
from typing import Dict, List

from charms.dp_pgbouncer_operator.v0 import pgb
from charms.operator_libs_linux.v0 import apt, passwd
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
        # add pgbouncer user to postgres group, created in above line
        passwd.add_user(
            username=self._pgb_user, password="pgb", primary_group="postgres"
        )
        u = pwd.getpwnam(self._pgb_user)
        self._postgres_gid = u.pw_gid
        self._pgbouncer_uid = u.pw_uid

        os.chown(PGB_DIR, self._pgbouncer_uid, self._postgres_gid)
        os.chown(INI_PATH, self._pgbouncer_uid, self._postgres_gid)
        os.chown(USERLIST_PATH, self._pgbouncer_uid, self._postgres_gid)
        os.setuid(self._pgbouncer_uid)

        # Initialise config files.
        # For now, use a dummy config dict - in future, we're going to have a static default
        # config file which may be overridden by a user uploading new files.
        initial_config = {
            "databases": {},
            "pgbouncer": {
                "logfile": f"{PGB_DIR}/pgbouncer.log",
                "pidfile": f"{PGB_DIR}/pgbouncer.pid",
                "admin_users": self.config["admin_users"].split(","),
            },
        }
        ini = pgb.PgbConfig(initial_config)
        self._render_pgb_config(ini)

        # Initialise userlist, generating passwords for initial users
        self._render_userlist(pgb.initialise_userlist_from_ini(ini))

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def _on_start(self, _) -> None:
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
        pass

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

    # =====================================
    #  PgBouncer-Specific Helper Functions
    # =====================================

    def _read_pgb_config(self) -> pgb.PgbConfig:
        """Get config object from pgbouncer.ini file.

        Returns:
            PgbConfig object containing pgbouncer config.
        """
        with open(INI_PATH, "r") as existing_file:
            existing_config = pgb.PgbConfig(existing_file.read())
        return existing_config

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
        self._render_file(INI_PATH, pgbouncer_ini.render(), 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _read_userlist(self) -> Dict[str, str]:
        with open(USERLIST_PATH, "r") as existing_userlist:
            userlist = pgb.parse_userlist(existing_userlist.read())
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
        self._render_file(USERLIST_PATH, pgb.generate_userlist(userlist), 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _reload_pgbouncer(self):
        pass


if __name__ == "__main__":
    main(PgBouncerCharm)
