# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, PropertyMock, call, patch

import ops.testing
import pytest
from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from charms.pgbouncer_k8s.v0 import pgb
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    RelationDataTypeError,
    WaitingStatus,
)
from ops.testing import Harness
from parameterized import parameterized

from charm import PgBouncerCharm
from constants import (
    BACKEND_RELATION_NAME,
    INI_NAME,
    PEER_RELATION_NAME,
    PGB_CONF_DIR,
    PGB_LOG_DIR,
    SECRET_INTERNAL_LABEL,
    SNAP_PACKAGES,
)
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

        self.rel_id = self.harness.add_relation(PEER_RELATION_NAME, self.charm.app.name)

    @pytest.fixture
    def use_caplog(self, caplog):
        self._caplog = caplog

    @patch("builtins.open", unittest.mock.mock_open())
    @patch("charm.snap.SnapCache")
    @patch("charm.PgBouncerCharm._install_snap_packages")
    @patch("charms.operator_libs_linux.v1.systemd.service_stop")
    @patch("os.makedirs")
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
        _makedirs,
        _stop,
        _install,
        _snap_cache,
    ):
        pg_snap = _snap_cache.return_value["charmed-postgresql"]
        self.charm.on.install.emit()

        _install.assert_called_once_with(packages=SNAP_PACKAGES)

        for service_id in self.charm.service_ids:
            _makedirs.assert_any_call(
                f"{PGB_CONF_DIR}/pgbouncer/instance_{service_id}", 0o700, exist_ok=True
            )
            _chown.assert_any_call(f"{PGB_CONF_DIR}/pgbouncer/instance_{service_id}", 1100, 120)

        # Check config files are rendered, including correct permissions
        initial_cfg = pgb.PgbConfig(DEFAULT_CFG)
        initial_cfg["pgbouncer"]["listen_addr"] = "127.0.0.1"
        initial_cfg["pgbouncer"]["user"] = "snap_daemon"
        _render_configs.assert_called_once_with(initial_cfg)
        pg_snap.alias.assert_called_once_with("psql")

        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=True,
    )
    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.systemd.service_running")
    @patch("charms.operator_libs_linux.v1.systemd.service_start", side_effect=systemd.SystemdError)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_on_start(self, _has_relation, _start, _, __, ___):
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
        calls = [call(f"pgbouncer-pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # Testing charm starts the correct amount of pgbouncer instances and enters activestatus if
        # everything's working fine.
        _start.reset_mock()
        _start.side_effect = None
        _has_relation.return_value = True
        self.charm.on.start.emit()
        calls = [call(f"pgbouncer-pgbouncer@{instance}") for instance in range(intended_instances)]
        _start.assert_has_calls(calls)
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_restart")
    @patch("charm.PgBouncerCharm.check_status", return_value=BlockedStatus())
    def test_reload_pgbouncer(self, _running, _restart):
        intended_instances = self._cores = os.cpu_count()
        self.charm.reload_pgbouncer()
        calls = [call(f"pgbouncer-pgbouncer@{instance}") for instance in range(intended_instances)]
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
        calls = [call("pgbouncer-pgbouncer@0")]
        _running.assert_has_calls(calls)
        _running.return_value = True

        # check fail when we can't get service status
        _running.side_effect = systemd.SystemdError
        self.assertIsInstance(self.charm.check_status(), BlockedStatus)
        _running.side_effect = None

        # otherwise check all services and return activestatus
        intended_instances = self._cores = os.cpu_count()
        self.assertIsInstance(self.charm.check_status(), ActiveStatus)
        calls = [
            call(f"pgbouncer-pgbouncer@{instance}") for instance in range(0, intended_instances)
        ]
        _running.assert_has_calls(calls)

    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=pgb.PgbConfig(DEFAULT_CFG))
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("relations.peers.Peers.app_databag", new_callable=PropertyMock)
    @patch_network_get(private_address="1.1.1.1")
    def test_on_config_changed(self, _app_databag, _render, _read):
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
        # _read.return_value is modified on config update, but the object reference is the same.
        _render.assert_called_with(_read.return_value, reload_pgbouncer=True)
        self.assertDictEqual(dict(_read.return_value), dict(test_config))

    @patch("charm.snap.SnapCache")
    def test_install_snap_packages(self, _snap_cache):
        _snap_package = _snap_cache.return_value.__getitem__.return_value
        _snap_package.ensure.side_effect = snap.SnapError
        _snap_package.present = False

        # Test for problem with snap update.
        with self.assertRaises(snap.SnapError):
            self.charm._install_snap_packages([("postgresql", {"channel": "14/edge"})])
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_cache.assert_called_once_with()
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="14/edge")

        # Test with a not found package.
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = snap.SnapNotFoundError
        with self.assertRaises(snap.SnapNotFoundError):
            self.charm._install_snap_packages([("postgresql", {"channel": "14/edge"})])
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_cache.assert_called_once_with()
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="14/edge")

        # Then test a valid one.
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = None
        self.charm._install_snap_packages([("postgresql", {"channel": "14/edge"})])
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="14/edge")
        _snap_package.hold.assert_not_called()

        # Test revision
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = None
        self.charm._install_snap_packages([("postgresql", {"revision": 42})])
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, revision=42)
        _snap_package.hold.assert_called_once_with()

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
        _getpwnam.assert_called_with("snap_daemon")
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
            cfg["pgbouncer"]["unix_socket_dir"] = f"/tmp/pgbouncer/instance_{service_id}"
            cfg["pgbouncer"][
                "logfile"
            ] = f"{PGB_LOG_DIR}/pgbouncer/instance_{service_id}/pgbouncer.log"
            cfg["pgbouncer"]["pidfile"] = f"/tmp/pgbouncer/instance_{service_id}/pgbouncer.pid"

            cfg_list.append(cfg.render())

        self.charm.render_pgb_config(default_cfg, reload_pgbouncer=False)

        _render.assert_any_call(f"{PGB_CONF_DIR}/pgbouncer/{INI_NAME}", cfg_list[0], 0o700)
        _render.assert_any_call(
            f"{PGB_CONF_DIR}/pgbouncer/instance_0/pgbouncer.ini", cfg_list[1], 0o700
        )
        _render.assert_any_call(
            f"{PGB_CONF_DIR}/pgbouncer/instance_1/pgbouncer.ini", cfg_list[2], 0o700
        )

        _reload.assert_not_called()
        # MaintenanceStatus will exit once pgbouncer reloads.
        self.assertIsInstance(self.harness.model.unit.status, MaintenanceStatus)

        self.charm.render_pgb_config(cfg, reload_pgbouncer=True)
        _reload.assert_called_once()

    #
    # Secrets
    #

    def test_scope_obj(self):
        assert self.charm._scope_obj("app") == self.charm.framework.model.app
        assert self.charm._scope_obj("unit") == self.charm.framework.model.unit
        assert self.charm._scope_obj("test") is None

    @patch_network_get(private_address="1.1.1.1")
    def test_get_secret(self):
        # App level changes require leader privileges
        with self.harness.hooks_disabled():
            self.harness.set_leader()
        # Test application scope.
        assert self.charm.get_secret("app", "password") is None
        self.harness.update_relation_data(
            self.rel_id, self.charm.app.name, {"password": "test-password"}
        )
        assert self.charm.get_secret("app", "password") == "test-password"

        # Unit level changes don't require leader privileges
        with self.harness.hooks_disabled():
            self.harness.set_leader(False)
        # Test unit scope.
        assert self.charm.get_secret("unit", "password") is None
        self.harness.update_relation_data(
            self.rel_id, self.charm.unit.name, {"password": "test-password"}
        )
        assert self.charm.get_secret("unit", "password") == "test-password"

    @parameterized.expand([("app"), ("unit")])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_get_secret_secrets(self, scope, _):
        with self.harness.hooks_disabled():
            self.harness.set_leader()

        assert self.charm.get_secret(scope, "operator-password") is None
        self.charm.set_secret(scope, "operator-password", "test-password")
        assert self.charm.get_secret(scope, "operator-password") == "test-password"

    @patch_network_get(private_address="1.1.1.1")
    def test_set_secret(self):
        with self.harness.hooks_disabled():
            self.harness.set_leader()

        # Test application scope.
        assert "password" not in self.harness.get_relation_data(self.rel_id, self.charm.app.name)
        self.charm.set_secret("app", "password", "test-password")
        assert (
            self.harness.get_relation_data(self.rel_id, self.charm.app.name)["password"]
            == "test-password"
        )
        self.charm.set_secret("app", "password", None)
        assert "password" not in self.harness.get_relation_data(self.rel_id, self.charm.app.name)

        # Test unit scope.
        assert "password" not in self.harness.get_relation_data(self.rel_id, self.charm.unit.name)
        self.charm.set_secret("unit", "password", "test-password")
        assert (
            self.harness.get_relation_data(self.rel_id, self.charm.unit.name)["password"]
            == "test-password"
        )
        self.charm.set_secret("unit", "password", None)
        assert "password" not in self.harness.get_relation_data(self.rel_id, self.charm.unit.name)

        with self.assertRaises(RuntimeError):
            self.charm.set_secret("test", "password", "test")

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_set_reset_new_secret(self, scope, is_leader, _):
        """NOTE: currently ops.testing seems to allow for non-leader to set secrets too!"""
        # App has to be leader, unit can be eithe
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)
        # Getting current password
        self.harness.charm.set_secret(scope, "new-secret", "bla")
        assert self.harness.charm.get_secret(scope, "new-secret") == "bla"

        # Reset new secret
        self.harness.charm.set_secret(scope, "new-secret", "blablabla")
        assert self.harness.charm.get_secret(scope, "new-secret") == "blablabla"

        # Set another new secret
        self.harness.charm.set_secret(scope, "new-secret2", "blablabla")
        assert self.harness.charm.get_secret(scope, "new-secret2") == "blablabla"

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_invalid_secret(self, scope, is_leader, _):
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        with self.assertRaises(RelationDataTypeError):
            self.harness.charm.set_secret(scope, "somekey", 1)

        self.harness.charm.set_secret(scope, "somekey", "")
        assert self.harness.charm.get_secret(scope, "somekey") is None

    @pytest.mark.usefixtures("use_caplog")
    @patch_network_get(private_address="1.1.1.1")
    def test_delete_password(self):
        """NOTE: currently ops.testing seems to allow for non-leader to remove secrets too!"""
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        self.harness.update_relation_data(
            self.rel_id, self.charm.app.name, {"replication": "somepw"}
        )
        self.harness.charm.remove_secret("app", "replication")
        assert self.harness.charm.get_secret("app", "replication") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(False)
        self.harness.update_relation_data(
            self.rel_id, self.charm.unit.name, {"somekey": "somevalue"}
        )
        self.harness.charm.remove_secret("unit", "somekey")
        assert self.harness.charm.get_secret("unit", "somekey") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        with self._caplog.at_level(logging.ERROR):
            self.harness.charm.remove_secret("app", "replication")
            assert (
                "Non-existing field 'replication' was attempted to be removed" in self._caplog.text
            )

            self.harness.charm.remove_secret("unit", "somekey")
            assert "Non-existing field 'somekey' was attempted to be removed" in self._caplog.text

            self.harness.charm.remove_secret("app", "non-existing-secret")
            assert (
                "Non-existing field 'non-existing-secret' was attempted to be removed"
                in self._caplog.text
            )

            self.harness.charm.remove_secret("unit", "non-existing-secret")
            assert (
                "Non-existing field 'non-existing-secret' was attempted to be removed"
                in self._caplog.text
            )

    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    @patch_network_get(private_address="1.1.1.1")
    @pytest.mark.usefixtures("use_caplog")
    def test_delete_existing_password_secrets(self, _):
        """NOTE: currently ops.testing seems to allow for non-leader to remove secrets too!"""
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        self.harness.charm.set_secret("app", "operator-password", "somepw")
        self.harness.charm.remove_secret("app", "operator-password")
        assert self.harness.charm.get_secret("app", "operator-password") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(False)
        self.harness.charm.set_secret("unit", "operator-password", "somesecret")
        self.harness.charm.remove_secret("unit", "operator-password")
        assert self.harness.charm.get_secret("unit", "operator-password") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        with self._caplog.at_level(logging.ERROR):
            self.harness.charm.remove_secret("app", "operator-password")
            assert (
                "Non-existing secret operator-password was attempted to be removed."
                in self._caplog.text
            )

            self.harness.charm.remove_secret("unit", "operator-password")
            assert (
                "Non-existing secret operator-password was attempted to be removed."
                in self._caplog.text
            )

            self.harness.charm.remove_secret("app", "non-existing-secret")
            assert (
                "Non-existing field 'non-existing-secret' was attempted to be removed"
                in self._caplog.text
            )

            self.harness.charm.remove_secret("unit", "non-existing-secret")
            assert (
                "Non-existing field 'non-existing-secret' was attempted to be removed"
                in self._caplog.text
            )

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_migration_from_databag(self, scope, is_leader, _):
        """Check if we're moving on to use secrets when live upgrade from databag to Secrets usage."""
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        # Getting current password
        entity = getattr(self.charm, scope)
        self.harness.update_relation_data(self.rel_id, entity.name, {"operator-password": "bla"})
        assert self.harness.charm.get_secret(scope, "operator-password") == "bla"

        # Reset new secret
        self.harness.charm.set_secret(scope, "operator-password", "blablabla")
        assert self.harness.charm.model.get_secret(label=f"pgbouncer.{scope}")
        assert self.harness.charm.get_secret(scope, "operator-password") == "blablabla"
        assert "operator-password" not in self.harness.get_relation_data(
            self.rel_id, getattr(self.charm, scope).name
        )

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_migration_from_single_secret(self, scope, is_leader, _):
        """Check if we're moving on to use secrets when live upgrade from databag to Secrets usage."""
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        secret = self.harness.charm.app.add_secret({"operator-password": "bla"})

        # Getting current password
        entity = getattr(self.charm, scope)
        self.harness.update_relation_data(
            self.rel_id, entity.name, {SECRET_INTERNAL_LABEL: secret.id}
        )
        assert self.harness.charm.get_secret(scope, "operator-password") == "bla"

        # Reset new secret
        # Only the leader can set app secret content.
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        self.harness.charm.set_secret(scope, "operator-password", "blablabla")
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)
        assert self.harness.charm.model.get_secret(label=f"pgbouncer.{scope}")
        assert self.harness.charm.get_secret(scope, "operator-password") == "blablabla"
        assert SECRET_INTERNAL_LABEL not in self.harness.get_relation_data(
            self.rel_id, getattr(self.charm, scope).name
        )
