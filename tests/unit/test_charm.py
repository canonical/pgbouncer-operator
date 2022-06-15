# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, call, patch

import ops.testing
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_operator.v0 import pgb
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import PgBouncerCharm

PGB_DIR = "/var/lib/postgresql/pgbouncer"
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

    @patch("charm.PgBouncerCharm._install_apt_packages")
    @patch("charms.operator_libs_linux.v1.systemd.service_stop")
    @patch("os.mkdir")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    @patch("charm.PgBouncerCharm._render_file")
    @patch("charm.PgBouncerCharm._render_service_configs")
    @patch("charms.pgbouncer_operator.v0.pgb.initialise_userlist_from_ini")
    @patch("shutil.copy")
    @patch("charms.operator_libs_linux.v1.systemd.daemon_reload")
    def test_on_install(
        self,
        _reload,
        _copy,
        _userlist,
        _render_configs,
        _render_file,
        _getpwnam,
        _chown,
        _mkdir,
        _stop,
        _install,
    ):
        _userlist.return_value = {"juju-admin": "test"}

        self.harness.charm.on.install.emit()

        _install.assert_called_with(["pgbouncer"])
        _mkdir.assert_any_call(PGB_DIR, 0o777)
        _chown.assert_any_call(PGB_DIR, 1100, 120)

        for service_id in self.harness.charm.service_ids:
            _mkdir.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 0o777)
            _chown.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 1100, 120)

        # Check config files are rendered, including correct permissions
        initial_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        initial_userlist = '"juju-admin" "test"'
        _render_configs.assert_called_once_with(initial_cfg)
        _render_file.assert_any_call(USERLIST_PATH, initial_userlist, 0o777)

        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_start", side_effect=systemd.SystemdError)
    @patch("charm.PgBouncerCharm._has_backend_relation", return_value=False)
    def test_on_start(self, _has_relation, _start):
        intended_instances = self._cores = os.cpu_count()
        # Testing charm blocks when systemd is in error
        self.harness.charm.on.start.emit()
        _start.assert_called()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # Testing charm starts the correct amount of pgbouncer instances but enters WaitingStatus
        # because the backend relation doesn't exist yet.
        _start.side_effect = None
        self.harness.charm.on.start.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

        # Testing charm starts the correct amount of pgbouncer instances and enters activestatus if
        # everything's working fine.
        _start.reset_mock()
        _start.side_effect = None
        _has_relation.return_value = True
        self.harness.charm.on.start.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_reload")
    def test_reload_pgbouncer(self, _reload):
        intended_instances = self._cores = os.cpu_count()
        self.harness.charm._reload_pgbouncer()
        calls = [
            call(f"pgbouncer@{instance}", restart_on_failure=True)
            for instance in range(intended_instances)
        ]
        _reload.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        # Verify that if systemd is in error, the charm enters blocked status.
        _reload.side_effect = systemd.SystemdError()
        self.harness.charm._reload_pgbouncer()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_running", return_value=False)
    @patch("charm.PgBouncerCharm._has_backend_relation", return_value=False)
    def test_on_update_status(self, _has_relation, _running):
        intended_instances = self._cores = os.cpu_count()
        # Testing charm blocks when the pgbouncer services aren't running
        self.harness.charm.on.update_status.emit()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # If all pgbouncer services are running, verify we wait for the backend relation.
        _running.return_value = True
        self.harness.charm.on.update_status.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _running.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

         # If all pgbouncer services are running and we have backend relation, set ActiveStatus.
        _running.reset_mock()
        _running.return_value = True
        _has_relation.return_value = True
        self.harness.charm.on.update_status.emit()
        _running.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        _running.side_effect = systemd.SystemdError()
        self.harness.charm.on.update_status.emit()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_config_changed(self, _render, _read):
        mock_cores = 1
        self.harness.charm._cores = mock_cores
        max_db_connections = 44

        # Copy config object and modify it as we expect in the hook.
        config = deepcopy(_read.return_value)
        config["pgbouncer"]["pool_mode"] = "transaction"
        config.set_max_db_connection_derivatives(
            max_db_connections=max_db_connections,
            pgb_instances=mock_cores,
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
        _getpwnam.assert_called_with("postgres")
        _chown.assert_called_with(path, uid=1100, gid=120)

    def test_read_pgb_config(self):
        with open(TEST_VALID_INI, "r") as ini:
            test_ini = ini.read()
            existing_config = pgb.PgbConfig(test_ini)

        with patch("builtins.open", unittest.mock.mock_open(read_data=test_ini)):
            test_config = self.harness.charm._read_pgb_config()

        self.assertEqual(test_ini, test_config.render())
        self.assertEqual(existing_config, test_config)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm._render_file")
    def test_render_pgb_config(self, _render, _reload):
        with open(TEST_VALID_INI, "r") as ini:
            test_config = pgb.PgbConfig(ini.read())

        self.harness.charm._render_pgb_config(test_config, reload_pgbouncer=False)
        _render.assert_called_with(INI_PATH, test_config.render(), 0o777)
        _reload.assert_not_called()

        # Copy config and edit a value
        reload_config = pgb.PgbConfig(deepcopy(test_config.__dict__))
        reload_config["pgbouncer"]["admin_users"] = ["test_admin"]

        self.harness.charm._render_pgb_config(reload_config, reload_pgbouncer=True)
        _render.assert_called_with(INI_PATH, reload_config.render(), 0o777)
        _reload.assert_called()

        self.harness.charm._render_pgb_config(reload_config, config_path="/test/path")
        _render.assert_called_with("/test/path", reload_config.render(), 0o777)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm._render_file")
    def test_render_service_configs(self, _render, _reload):
        self.harness.charm.service_ids = [0, 1]
        default_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        cfg_list = [default_cfg.render()]

        for service_id in self.harness.charm.service_ids:
            cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
            instance_dir = f"{PGB_DIR}/instance_{service_id}"

            cfg["pgbouncer"]["unix_socket_dir"] = instance_dir
            cfg["pgbouncer"]["logfile"] = f"{instance_dir}/pgbouncer.log"
            cfg["pgbouncer"]["pidfile"] = f"{instance_dir}/pgbouncer.pid"

            cfg_list.append(cfg.render())

        self.harness.charm._render_service_configs(default_cfg, reload_pgbouncer=False)

        _render.assert_any_call(INI_PATH, cfg_list[0], 0o777)
        _render.assert_any_call(f"{PGB_DIR}/instance_0/pgbouncer.ini", cfg_list[1], 0o777)
        _render.assert_any_call(f"{PGB_DIR}/instance_1/pgbouncer.ini", cfg_list[2], 0o777)

        _reload.assert_not_called()
        # MaintenanceStatus will exit once pgbouncer reloads.
        self.assertIsInstance(self.harness.model.unit.status, MaintenanceStatus)

        self.harness.charm._render_service_configs(cfg, reload_pgbouncer=True)
        _reload.assert_called_once()

    def test_read_userlist(self):
        test_users = {"test_user": "test_pass"}
        test_userlist = '"test_user" "test_pass"'

        with patch("builtins.open", unittest.mock.mock_open(read_data=test_userlist)):
            output = self.harness.charm._read_userlist()
        self.assertEqual(test_users, output)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm._render_file")
    def test_render_userlist(self, _render, _reload):
        test_users = {"test_user": "test_pass"}

        self.harness.charm._render_userlist(test_users, reload_pgbouncer=False)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(test_users), 0o777)
        _reload.assert_not_called()

        reload_users = {"reload_user": "reload_pass"}
        self.harness.charm._render_userlist(reload_users, reload_pgbouncer=True)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(reload_users), 0o777)
        _reload.assert_called()
