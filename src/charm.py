#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler."""

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

INI_PATH = "/etc/pgbouncer/pgbouncer.ini"
USERLIST_PATH = "/etc/pgbouncer/userlist.txt"


"""
EOD TODO
install dummy pgbouncer.ini and userlist.txt files
write dosctrings for methods
get charm installing and running
write unit tests
manual test
write integration tests (build and deploy, change config)
open pr
"""


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._pgbouncer_service = "pgbouncer"

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

        passwd.add_user(username="pgbouncer", password="pgb")
        self._install_apt_packages(["pgbouncer"])
        self._update_local_config()

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def _on_start(self, _) -> None:

        try:
            command = [
                "pgbouncer",
                INI_PATH,
            ]
            logger.debug(f"pgbouncer call: {' '.join(command)}")
            subprocess.check_call(command)
        except subprocess.CalledProcessError as e:
            logger.info(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")
        self.unit.status = ActiveStatus("pgbouncer started")

    def _on_config_changed(self, _) -> None:
        pass

    # ==================
    #  Helper Functions
    # ==================

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
        except apt.PackageNotFoundError:
            logger.error("a specified package not found in package cache or on system")
            self.unit.status = BlockedStatus("failed to install packages")

    def _update_local_config(
        self, users: Dict[str, str] = None, reload_pgbouncer: bool = False
    ) -> None:
        """Updates config files stored on pgbouncer machine and reloads application.

        Updates userlist.txt and pgbouncer.ini config files, reloading pgbouncer application once
        updated.

        Args:
            users: a dictionary of usernames and passwords
            reload_pgbouncer: A boolean defining whether or not to reload pgbouncer after updating
                the config. PgBouncer must be restarted for config changes to be applied.
        """
        if users is None:
            users = self._retrieve_users_from_userlist()
        else:
            self._update_userlist(users)

        self._update_pgbouncer_ini(users, reload_pgbouncer)

    def _update_pgbouncer_ini(
        self, users: Dict[str, str] = None, reload_pgbouncer: bool = False
    ) -> None:
        """Generate pgbouncer.ini from juju config and deploy it to the container.

        Args:
            users: a dictionary of usernames and passwords
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer application
                in the container. When config files are updated, pgbouncer must be restarted for
                the changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        if users is None:
            users = self._retrieve_users_from_userlist()

        pgb_ini = pgb.generate_pgbouncer_ini(users, self.config)
        self._render_file(pgb_ini, INI_PATH, 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _update_userlist(self, users: Dict[str, str], reload_pgbouncer: bool = False):
        userlist = pgb.generate_userlist(users)
        self._render_file(userlist, USERLIST_PATH, 0o600)

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _retrieve_users_from_userlist(self):
        return {"coolguy": "securepass"}

    def _reload_pgbouncer(self):
        pass

    def _render_file(self, path: str, content: str, mode: int) -> None:
        """Write a content rendered from a template to a file.

        Args:
            path: the path to the file.
            content: the data to be written to the file.
            mode: access permission mask applied to the
            file using chmod (e.g. 0o640).
        """
        logger.info(f"rendering file \n{content}")
        with open(path, "w+") as file:
            file.write(content)
        # Ensure correct permissions are set on the file.
        os.chmod(path, mode)
        # Get the uid/gid for the pgbouncer user.
        u = pwd.getpwnam("pgbouncer")
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)


if __name__ == "__main__":
    main(PgBouncerCharm)
