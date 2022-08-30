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
from constants import INI_PATH, PGB, PGB_DIR, USERLIST_PATH

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

    @patch("charm.PgBouncerCharm._install_apt_packages")
    @patch("charms.operator_libs_linux.v1.systemd.service_stop")
    @patch("os.mkdir")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    @patch("charm.PgBouncerCharm.render_file")
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

        self.charm.on.install.emit()

        _install.assert_called_with(["pgbouncer"])
        _mkdir.assert_any_call(PGB_DIR, 0o700)
        _chown.assert_any_call(PGB_DIR, 1100, 120)

        for service_id in self.charm.service_ids:
            _mkdir.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 0o700)
            _chown.assert_any_call(f"{PGB_DIR}/instance_{service_id}", 1100, 120)

        # Check config files are rendered, including correct permissions
        initial_cfg = pgb.PgbConfig(DEFAULT_CFG)
        initial_userlist = '"juju-admin" "test"'
        _render_configs.assert_called_once_with(initial_cfg)
        _render_file.assert_any_call(USERLIST_PATH, initial_userlist, 0o700)

        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_start", side_effect=systemd.SystemdError)
    @patch("charm.PgBouncerCharm._has_backend_relation", return_value=False)
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

    @patch("charms.operator_libs_linux.v1.systemd.service_reload")
    def test_reload_pgbouncer(self, _reload):
        intended_instances = self._cores = os.cpu_count()
        self.charm._reload_pgbouncer()
        calls = [
            call(f"pgbouncer@{instance}", restart_on_failure=True)
            for instance in range(intended_instances)
        ]
        _reload.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        # Verify that if systemd is in error, the charm enters blocked status.
        _reload.side_effect = systemd.SystemdError()
        self.charm._reload_pgbouncer()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_running", return_value=False)
    @patch("charm.PgBouncerCharm._has_backend_relation", return_value=False)
    def test_on_update_status(self, _has_relation, _running):
        intended_instances = self._cores = os.cpu_count()
        # Testing charm blocks when the pgbouncer services aren't running
        self.charm.on.update_status.emit()
        # Verify we immediately block once we know we have services that aren't running.
        _running.assert_called_once()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # If all pgbouncer services are running but we have no backend relation, verify we block &
        # wait for the backend relation.
        _running.return_value = True
        self.charm.on.update_status.emit()
        calls = [call(f"pgbouncer@{instance}") for instance in range(intended_instances)]
        _running.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # If all pgbouncer services are running and we have backend relation, set ActiveStatus.
        _running.reset_mock()
        _running.return_value = True
        _has_relation.return_value = True
        self.charm.on.update_status.emit()
        _running.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        _running.side_effect = systemd.SystemdError()
        self.charm.on.update_status.emit()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    @patch("charm.PgBouncerCharm.unit_ip")
    def test_on_config_changed(self, _unit_ip, _render, _read):
        mock_cores = 1
        ip = "1.1.1.1"
        self.charm.unit_ip = ip
        self.charm._cores = mock_cores
        max_db_connections = 44

        # Copy config object and modify it as we expect in the hook.
        config = deepcopy(_read.return_value)
        config["pgbouncer"]["pool_mode"] = "transaction"
        config["pgbouncer"]["listen_addr"] = ip
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

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_file")
    def test_render_pgb_config(self, _render, _reload):
        with open(TEST_VALID_INI, "r") as ini:
            test_config = pgb.PgbConfig(ini.read())

        self.charm._render_pgb_config(test_config, reload_pgbouncer=False)
        _render.assert_called_with(INI_PATH, test_config.render(), 0o700)
        _reload.assert_not_called()

        # Copy config and edit a value
        reload_config = pgb.PgbConfig(deepcopy(test_config.__dict__))
        reload_config["pgbouncer"]["admin_users"] = ["test_admin"]

        self.charm._render_pgb_config(reload_config, reload_pgbouncer=True)
        _render.assert_called_with(INI_PATH, reload_config.render(), 0o700)
        _reload.assert_called()

        self.charm._render_pgb_config(reload_config, config_path="/test/path")
        _render.assert_called_with("/test/path", reload_config.render(), 0o700)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_file")
    def test_render_service_configs(self, _render, _reload):
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

        self.charm._render_service_configs(default_cfg, reload_pgbouncer=False)

        _render.assert_any_call(INI_PATH, cfg_list[0], 0o700)
        _render.assert_any_call(f"{PGB_DIR}/instance_0/pgbouncer.ini", cfg_list[1], 0o700)
        _render.assert_any_call(f"{PGB_DIR}/instance_1/pgbouncer.ini", cfg_list[2], 0o700)

        _reload.assert_not_called()
        # MaintenanceStatus will exit once pgbouncer reloads.
        self.assertIsInstance(self.harness.model.unit.status, MaintenanceStatus)

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)
        _reload.assert_called_once()

    def test_read_userlist(self):
        test_users = {"test_user": "test_pass"}
        test_userlist = '"test_user" "test_pass"'

        with patch("builtins.open", unittest.mock.mock_open(read_data=test_userlist)):
            output = self.charm._read_userlist()
        self.assertEqual(test_users, output)

    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_file")
    def test_render_userlist(self, _render, _reload):
        test_users = {"test_user": "test_pass"}

        self.charm._render_userlist(test_users, reload_pgbouncer=False)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(test_users), 0o700)
        _reload.assert_not_called()

        reload_users = {"reload_user": "reload_pass"}
        self.charm._render_userlist(reload_users, reload_pgbouncer=True)
        _render.assert_called_with(USERLIST_PATH, pgb.generate_userlist(reload_users), 0o700)
        _reload.assert_called()

    @patch("charms.pgbouncer_operator.v0.pgb.generate_password", return_value="default-pass")
    @patch("charm.PgBouncerCharm._read_userlist", return_value={})
    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.PgBouncerCharm._render_userlist")
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_add_user(self, _render_cfg, _render_userlist, _read_cfg, _read_userlist, _gen_pw):
        default_admins = DEFAULT_CFG[PGB]["admin_users"]
        default_stats = DEFAULT_CFG[PGB]["stats_users"]

        # If user already exists, assert we aren't recreating them.
        _read_userlist.return_value = {"test-user": "test-pass"}
        self.charm.add_user(user="test-user", password="test-pass")
        _render_userlist.assert_not_called()
        _read_userlist.reset_mock()

        # Test defaults
        cfg = pgb.PgbConfig(DEFAULT_CFG)
        self.charm.add_user(user="test-user", cfg=cfg)
        _render_userlist.assert_called_with({"test-user": "default-pass"})
        _render_cfg.assert_not_called()
        assert cfg[PGB].get("admin_users") == default_admins
        # No stats_users by default
        assert cfg[PGB].get("stats_users") == default_stats
        _read_userlist.reset_mock()
        _render_userlist.reset_mock()

        # Test everything else
        max_cfg = pgb.PgbConfig(DEFAULT_CFG)
        self.charm.add_user(
            user="max-test",
            password="max-pw",
            cfg=max_cfg,
            admin=True,
            stats=True,
            reload_pgbouncer=True,
            render_cfg=True,
        )
        _render_userlist.assert_called_with({"test-user": "default-pass", "max-test": "max-pw"})
        assert max_cfg[PGB].get("admin_users") == default_admins + ["max-test"]
        assert max_cfg[PGB].get("stats_users") == default_stats + ["max-test"]
        _render_cfg.assert_called_with(max_cfg, True)

        # Test we can't duplicate stats or admin users
        self.charm.add_user(
            user="max-test", password="max-pw", cfg=max_cfg, admin=True, stats=True
        )
        assert max_cfg[PGB].get("admin_users") == default_admins + ["max-test"]
        assert max_cfg[PGB].get("stats_users") == default_stats + ["max-test"]

    @patch("charm.PgBouncerCharm._read_userlist", return_value={"test_user": ""})
    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.PgBouncerCharm._render_userlist")
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_remove_user(self, _render_cfg, _render_userlist, _read_cfg, _read_userlist):
        user = "test_user"
        cfg = pgb.PgbConfig(DEFAULT_CFG)
        cfg[PGB]["admin_users"].append(user)
        cfg[PGB]["stats_users"].append(user)
        admin_users = list(cfg[PGB]["admin_users"])
        stats_users = list(cfg[PGB]["stats_users"])

        # try to remove user that doesn't exist
        self.charm.remove_user("nonexistent-user", cfg=cfg)
        _render_userlist.assert_not_called()
        assert cfg[PGB]["admin_users"] == admin_users
        assert cfg[PGB]["stats_users"] == stats_users

        # remove user that does exist
        self.charm.remove_user(user, cfg=cfg, render_cfg=True, reload_pgbouncer=True)
        assert user not in cfg[PGB]["admin_users"]
        assert user not in cfg[PGB]["stats_users"]
        _render_userlist.assert_called_with({})
        _render_cfg.assert_called_with(cfg, True)
