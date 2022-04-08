# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

import ops.testing
from charms.operator_libs_linux.v0 import apt
from charms.pgbouncer_operator.v0 import pgb
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import PgBouncerCharm

PGB_DIR = "/etc/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
USERLIST_PATH = f"{PGB_DIR}/userlist.txt"

DATA_DIR = "tests/unit/data"
TEST_VALID_INI = f"{DATA_DIR}/test.ini"

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("charms.operator_libs_linux.v0.passwd.add_user")
    @patch("charms.pgbouncer_operator.v0.pgb.initialise_userlist_from_ini")
    @patch("charms.pgbouncer_operator.v0.pgb.generate_password", return_value="pgb")
    @patch("charm.PgBouncerCharm._install_apt_packages")
    @patch("charm.PgBouncerCharm._render_file")
    @patch("os.setuid")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    def test_on_install(
        self, _getpwnam, _chown, _setuid, _render_file, _install, _password, _userlist, _add_user
    ):
        _userlist.return_value = {"juju-admin": "test"}

        self.harness.charm.on.install.emit()

        _install.assert_called_with(["pgbouncer"])
        _add_user.assert_called_with(
            username="pgbouncer", password="pgb", primary_group="postgres"
        )

        # Assert files are written with the correct permissions
        pgb_uid = 1100
        pg_gid = 120
        _chown.assert_any_call(USERLIST_PATH, pgb_uid, pg_gid)
        _chown.assert_any_call(INI_PATH, pgb_uid, pg_gid)
        _chown.assert_any_call(PGB_DIR, pgb_uid, pg_gid)
        _setuid.assert_called_with(pgb_uid)

        # Check default config files are rendered correctly, including correct permissions
        initial_pgbouncer_ini = pgb.PgbConfig(pgb.DEFAULT_CONFIG).render()
        initial_userlist = '"juju-admin" "test"'
        _render_file.assert_any_call(INI_PATH, initial_pgbouncer_ini, 0o600)
        _render_file.assert_any_call(USERLIST_PATH, initial_userlist, 0o600)

        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting to start PgBouncer"),
        )

    @patch("os.setuid")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    @patch("subprocess.check_call")
    def test_on_start(self, _call, _getpwnam, _setuid):
        self.harness.charm.on.start.emit()
        _setuid.assert_called_with(1100)
        command = ["pgbouncer", "-d", INI_PATH]
        _call.assert_called_with(command)
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("pgbouncer started"))

        _call.side_effect = subprocess.CalledProcessError(returncode=999, cmd="fail test case")
        self.harness.charm.on.start.emit()
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("failed to start pgbouncer")
        )

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_pgb_config")
    @patch("os.cpu_count", return_value=1)
    def test_on_config_changed(self, _cpu_count, _render, _read):
        max_db_connections = 44
        # Copy config object and modify it as we expect in the hook.
        config = deepcopy(_read.return_value)
        config["pgbouncer"]["pool_mode"] = "transaction"
        config.set_max_db_connection_derivatives(
            max_db_connections=max_db_connections,
            pgb_instances=_cpu_count.return_value,
        )

        # set config to include pool_mode and max_db_connections
        self.harness.update_config(
            {
                "pool_mode": "transaction",
                "max_db_connections": max_db_connections,
            }
        )

        _read.assert_called_once()
        # _read.return_value is modified on config update, but the object reference is the same.
        _render.assert_called_with(_read.return_value, reload_pgbouncer=True)

        self.assertDictEqual(dict(_read.return_value), dict(config))

    @patch("charms.operator_libs_linux.v0.apt.add_package")
    @patch("charms.operator_libs_linux.v0.apt.update")
    def test_install_apt_packages(self, _update, _add_package):
        self.harness.charm._install_apt_packages(["test_package"])
        _update.assert_called_once()
        _add_package.assert_called_with(["test_package"])

        _add_package.side_effect = apt.PackageNotFoundError()
        self.harness.charm._install_apt_packages(["fail_to_install"])
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("failed to install packages")
        )

        _update.side_effect = subprocess.CalledProcessError(returncode=999, cmd="fail to update")
        self.harness.charm._install_apt_packages(["fail_to_update_apt_cache"])
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("failed to update apt cache")
        )

    @patch("os.chmod")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    def test_render_file(self, _getpwnam, _chown, _chmod):
        path = "test/test_render_file.txt"
        content = "this text file should never be written"
        mode = 0o777
        with patch("builtins.open", unittest.mock.mock_open()) as _:
            self.harness.charm._render_file(path, content, mode)

        _chmod.assert_called_with(path, mode)
        _getpwnam.assert_called_with("pgbouncer")
        _chown.assert_called_with(path, uid=1100, gid=120)

    @patch("charm.PgBouncerCharm._read_file")
    def test_read_pgb_config(self, _read):
        with open(TEST_VALID_INI, "r") as ini:
            test_ini = ini.read()
            existing_config = pgb.PgbConfig(test_ini)

        _read.return_value = test_ini
        test_config = self.harness.charm._read_pgb_config()

        self.assertEqual(test_ini, test_config.render())
        self.assertEqual(existing_config, test_config)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm._render_file")
    def test_render_pgb_config(self, _render, _reload):
        with open(TEST_VALID_INI, "r") as ini:
            test_config = pgb.PgbConfig(ini.read())

        self.harness.charm._render_pgb_config(test_config, reload_pgbouncer=False)
        _render.assert_called_with(INI_PATH, test_config.render(), 0o600)
        _reload.assert_not_called()

        # Copy config and edit a value
        reload_config = pgb.PgbConfig(deepcopy(test_config.__dict__))
        reload_config["pgbouncer"]["admin_users"] = ["test_admin"]

        self.harness.charm._render_pgb_config(reload_config, reload_pgbouncer=True)
        _render.assert_called_with(INI_PATH, reload_config.render(), 0o600)
        _reload.assert_called()

    @patch("charm.PgBouncerCharm._read_file", return_value='"test_user" "test_pass"')
    def test_read_userlist(self, _read):
        test_users = {"test_user": "test_pass"}
        output = self.harness.charm._read_userlist()
        self.assertEqual(test_users, output)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm._render_file")
    def test_render_userlist(self, _render, _reload):
        test_users = {"test_user": "test_pass"}

        self.harness.charm._render_userlist(test_users, reload_pgbouncer=False)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(test_users), 0o600)
        _reload.assert_not_called()

        reload_users = {"reload_user": "reload_pass"}
        self.harness.charm._render_userlist(reload_users, reload_pgbouncer=True)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(reload_users), 0o600)
        _reload.assert_called()
