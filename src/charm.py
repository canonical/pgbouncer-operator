#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler."""

import logging
import subprocess
from typing import List

from lib.charms.operator_libs_linux.v0 import apt
from lib.charms.dp_pgbouncer_operator.v0 import pgb
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
write docstrings for charm lib
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
        self.unit.status = MaintenanceStatus("Installing and configuring PgBouncer")

        self._install_apt_packages(["pgbouncer"])
        self._update_local_config()

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def _on_start(self, _) -> None:

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

    def _update_local_config(self, users=None) -> None:
        """Updates config files stored on pgbouncer machine and reloads application.

        Updates userlist.txt and pgbouncer.ini config files, reloading pgbouncer application once
        updated.

        Params:
            users: a dictionary of usernames and passwords
        """
        if users is None:
            users = self._get_userlist_from_machine()
        else:
            self._push_userlist(users)

        self._push_pgbouncer_ini(users, reload_pgbouncer=True)

    def _push_pgbouncer_ini(self, users=None, reload_pgbouncer=False) -> None:
        """Generate pgbouncer.ini from juju config and deploy it to the container.

        Params:
            users: a dictionary of usernames and passwords
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer application
                in the container. When config files are updated, pgbouncer must be restarted for
                the changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        if users is None:
            users = self._get_userlist_from_machine()

        pgbouncer_ini = pgb.generate_pgbouncer_ini(users)
        # try:
        #     # Check that we're not updating this file unnecessarily
        #     if pgb_container.pull(INI_PATH).read() == pgbouncer_ini:
        #         logger.info("updated config does not modify existing pgbouncer config")
        #         return
        # except FileNotFoundError:
        #     # There is no existing pgbouncer.ini file, so carry on and add one.
        #     pass

        # pgb_container.push(
        #     INI_PATH,
        #     pgbouncer_ini,
        #     user=self._pgbouncer_user,
        #     permissions=0o600,
        #     make_dirs=True,
        # )
        logging.info("initialised pgbouncer.ini file")

        if reload_pgbouncer:
            self._reload_pgbouncer()

    def _push_userlist(self):
        pass

    def _get_userlist_from_machine(self):
        pass

    def _reload_pgbouncer(self):
        pass


if __name__ == "__main__":
    main(PgBouncerCharm)
