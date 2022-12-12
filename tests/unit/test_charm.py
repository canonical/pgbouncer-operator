# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, PropertyMock, call, patch

import ops.testing
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_k8s.v0 import pgb
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_RELATION_NAME, INI_PATH, PGB_DIR
from tests.helpers import patch_network_get

DATA_DIR = "tests/unit/data"
TEST_VALID_INI = f"{DATA_DIR}/test.ini"
DEFAULT_CFG = pgb.DEFAULT_CONFIG

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.unit = self.harness.charm.unit

    @patch("charm.PgBouncerCharm._install_apt_packages")
    @patch("charms.operator_libs_linux.v1.systemd.service_stop")
    @patch("os.mkdir")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    @patch("charm.PgBouncerCharm.render_file")
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("shutil.copy")
    @patch("charms.operator_libs_linux.v1.systemd.daemon_reload")
    def test_on_install(
        self,
        _reload,
        _copy,
        _render_configs,
        _render_file,
        _getpwnam,
        _chown,
        _mkdir,
        _stop,
        _install,
    ):
        self.charm.on.install.emit()

        _install.assert_called_with(["pgbouncer"])
        _mkdir.assert_any_call(PGB_DIR, 0o700)
        _chown.assert_any_call(PGB_DIR, 1100, 120)

        for service_id in self.charm.service_ids:
            _mkdir.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 0o700)
            _chown.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 1100, 120)

        # Check config files are rendered, including correct permissions
        initial_cfg = pgb.PgbConfig(DEFAULT_CFG)
        _render_configs.assert_called_once_with(initial_cfg)

        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_start", side_effect=systemd.SystemdError)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_on_start(self, _has_relation, _start):
        intended_instances = self._cores = os.cpu_count()
        # Testing charm blocks when systemd is in error
        self.charm.on.start.emit()
        # Charm should fail out after calling _start once
        _start.assert_called_once()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # Testing charm starts the correct amount of pgbouncer instances but enters BlockedStatus
        # because the backend relation doesn't exist yet.
        _start.side_effect = None
        self.charm.on.start.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # Testing charm starts the correct amount of pgbouncer instances and enters activestatus if
        # everything's working fine.
        _start.reset_mock()
        _start.side_effect = None
        _has_relation.return_value = True
        self.charm.on.start.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_restart")
    @patch("charm.PgBouncerCharm.check_status", return_value=BlockedStatus())
    def test_reload_pgbouncer(self, _running, _restart):
        intended_instances = self._cores = os.cpu_count()
        self.charm.reload_pgbouncer()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _restart.assert_has_calls(calls)
        _running.assert_called_once()

        # Verify that if systemd is in error, the charm enters blocked status.
        _restart.side_effect = systemd.SystemdError()
        self.charm.reload_pgbouncer()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charm.PgBouncerCharm.read_pgb_config", side_effect=FileNotFoundError)
    @patch("charms.operator_libs_linux.v1.systemd.service_running", return_value=False)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=False,
    )
    def test_check_status(self, _postgres_ready, _running, _read_cfg):
        # check fail on config not available
        self.assertIsInstance(self.charm.check_status(), WaitingStatus)
        _read_cfg.side_effect = None

        # check fail on postgres not available
        # Testing charm blocks when the pgbouncer services aren't running
        self.assertIsInstance(self.charm.check_status(), BlockedStatus)
        _postgres_ready.return_value = True

        # check fail when services aren't all running
        self.assertIsInstance(self.charm.check_status(), BlockedStatus)
        calls = [call("pgbouncer@0")]
        _running.assert_has_calls(calls)
        _running.return_value = True

        # check fail when we can't get service status
        _running.side_effect = systemd.SystemdError
        self.assertIsInstance(self.charm.check_status(), BlockedStatus)
        _running.side_effect = None

        # otherwise check all services and return activestatus
        intended_instances = self._cores = os.cpu_count()
        self.assertIsInstance(self.charm.check_status(), ActiveStatus)
        calls = [call(f"pgbouncer@{instance}") for instance in range(0, intended_instances)]
        _running.assert_has_calls(calls)

    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.update_systemd_socket")
    @patch("relations.peers.Peers.app_databag", new_callable=PropertyMock)
    @patch_network_get(private_address="1.1.1.1")
    def test_on_config_changed(self, _app_databag, _update_socket, _render, _read):
        self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.harness.set_leader()
        mock_cores = 1
        self.charm._cores = mock_cores
        max_db_connections = 44

        # Copy config object and modify it as we expect in the hook.
        test_config = deepcopy(_read.return_value)
        test_config["pgbouncer"]["pool_mode"] = "transaction"
        test_config.set_max_db_connection_derivatives(
            max_db_connections=max_db_connections,
            pgb_instances=mock_cores,
        )

        test_config["pgbouncer"]["listen_port"] = 6464

        # set config to include pool_mode and max_db_connections
        self.harness.update_config(
            {
                "pool_mode": "transaction",
                "max_db_connections": max_db_connections,
                "listen_port": 6464,
            }
        )

        _read.assert_called_once()
        _update_socket.assert_called_once()
        # _read.return_value is modified on config update, but the object reference is the same.
        _render.assert_called_with(_read.return_value, reload_pgbouncer=True)
        self.assertDictEqual(dict(_read.return_value), dict(test_config))

    @patch("charms.operator_libs_linux.v0.apt.add_package")
    @patch("charms.operator_libs_linux.v0.apt.update")
    def test_install_apt_packages(self, _update, _add_package):
        self.charm._install_apt_packages(["test_package"])
        _update.assert_called_once()
        _add_package.assert_called_with(["test_package"])

        _add_package.side_effect = apt.PackageNotFoundError()
        self.charm._install_apt_packages(["fail_to_install"])
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("failed to install packages")
        )

        _update.side_effect = subprocess.CalledProcessError(returncode=999, cmd="fail to update")
        self.charm._install_apt_packages(["fail_to_update_apt_cache"])
        self.assertEqual(
            self.harness.model.unit.status, BlockedStatus("failed to update apt cache")
        )

    @patch("os.chmod")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    def test_render_file(self, _getpwnam, _chown, _chmod):
        path = "test/test_render_file.txt"
        content = "this text file should never be written"
        mode = 0o700
        with patch("builtins.open", unittest.mock.mock_open()) as _:
            self.charm.render_file(path, content, mode)

        _chmod.assert_called_with(path, mode)
        _getpwnam.assert_called_with("postgres")
        _chown.assert_called_with(path, uid=1100, gid=120)

    def test_read_pgb_config(self):
        with open(TEST_VALID_INI, "r") as ini:
            test_ini = ini.read()
            existing_config = pgb.PgbConfig(test_ini)

        with patch("builtins.open", unittest.mock.mock_open(read_data=test_ini)):
            test_config = self.charm.read_pgb_config()

        self.assertEqual(test_ini, test_config.render())
        self.assertEqual(existing_config, test_config)

    @patch("charm.PgBouncerCharm.reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_file")
    def test_render_pgb_config(self, _render, _reload):
        self.charm.service_ids = [0, 1]
        default_cfg = pgb.PgbConfig(DEFAULT_CFG)
        cfg_list = [default_cfg.render()]

        for service_id in self.charm.service_ids:
            cfg = pgb.PgbConfig(DEFAULT_CFG)
            instance_dir = f"{PGB_DIR}/instance_{service_id}"

            cfg["pgbouncer"]["unix_socket_dir"] = instance_dir
            cfg["pgbouncer"]["logfile"] = f"{instance_dir}/pgbouncer.log"
            cfg["pgbouncer"]["pidfile"] = f"{instance_dir}/pgbouncer.pid"

            cfg_list.append(cfg.render())

        self.charm.render_pgb_config(default_cfg, reload_pgbouncer=False)

        _render.assert_any_call(INI_PATH, cfg_list[0], 0o700)
        _render.assert_any_call(f"{PGB_DIR}/instance_0/pgbouncer.ini", cfg_list[1], 0o700)
        _render.assert_any_call(f"{PGB_DIR}/instance_1/pgbouncer.ini", cfg_list[2], 0o700)

        _reload.assert_not_called()
        # MaintenanceStatus will exit once pgbouncer reloads.
        self.assertIsInstance(self.harness.model.unit.status, MaintenanceStatus)

        self.charm.render_pgb_config(cfg, reload_pgbouncer=True)
        _reload.assert_called_once()
