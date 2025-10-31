# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import math
import platform
import unittest
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch

import ops.testing
import psycopg2
import pytest
from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from jinja2 import Template
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    JujuVersion,
    RelationDataTypeError,
    WaitingStatus,
)
from ops.testing import Harness
from parameterized import parameterized

from charm import PgBouncerCharm
from constants import (
    BACKEND_RELATION_NAME,
    EXTENSIONS_BLOCKING_MESSAGE,
    PEER_RELATION_NAME,
    PGB_CONF_DIR,
    PGB_LOG_DIR,
    PGB_RUN_DIR,
    SECRET_INTERNAL_LABEL,
    SNAP_PACKAGES,
)

DATA_DIR = "tests/unit/data"
TEST_VALID_INI = f"{DATA_DIR}/test.ini"

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.unit = self.harness.charm.unit

        self.harness.add_relation("upgrade", self.charm.app.name)
        self.rel_id = self.harness.add_relation(PEER_RELATION_NAME, self.charm.app.name)

    @pytest.fixture
    def use_caplog(self, caplog):
        self._caplog = caplog

    @patch("charm.logger.warning")
    @patch("builtins.open", unittest.mock.mock_open())
    @patch("charm.snap.SnapCache")
    @patch("charm.PgBouncerCharm._install_snap_packages")
    @patch("charms.operator_libs_linux.v1.systemd.service_stop")
    @patch("os.makedirs")
    @patch("os.chown")
    @patch("pwd.getpwnam", return_value=MagicMock(pw_uid=1100, pw_gid=120))
    @patch("charm.PgBouncerCharm.render_file")
    @patch("shutil.copy")
    @patch("charms.operator_libs_linux.v1.systemd.daemon_reload")
    def test_on_install(
        self,
        _reload,
        _copy,
        _render_file,
        _getpwnam,
        _chown,
        _makedirs,
        _stop,
        _install,
        _snap_cache,
        _warning,
    ):
        pg_snap = _snap_cache.return_value["charmed-pgbouncer"]
        self.charm.on.install.emit()

        _install.assert_called_once_with(packages=SNAP_PACKAGES)

        for service_id in self.charm.service_ids:
            _makedirs.assert_any_call(
                f"{PGB_CONF_DIR}/pgbouncer/instance_{service_id}", 0o700, exist_ok=True
            )
            _chown.assert_any_call(f"{PGB_CONF_DIR}/pgbouncer/instance_{service_id}", 1100, 120)

        # Check config files are rendered, including correct permissions
        pg_snap.alias.assert_called_once_with("psql")

        self.assertIsInstance(self.harness.model.unit.status, WaitingStatus)

        # Log warning if alias fails
        pg_snap.alias.side_effect = snap.SnapError

        self.charm.on.install.emit()

        _warning.assert_called_once_with("Unable to create alias")

    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=True,
    )
    @patch("charm.systemd.service_running")
    @patch("charm.PgBouncerCharm.render_prometheus_service")
    @patch("charms.operator_libs_linux.v1.systemd.service_start", side_effect=systemd.SystemdError)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_on_start(self, _has_relation, _start, _render_prom_service, _, __):
        with self.harness.hooks_disabled():
            self.harness.update_relation_data(
                self.rel_id, self.charm.unit.name, {"userlist_nonce": "test"}
            )
        # Testing charm blocks when systemd is in error
        self.charm.on.start.emit()
        # Charm should fail out after calling _start once
        _start.assert_called_once()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        _start.reset_mock()

        # Testing charm starts the correct amount of pgbouncer instances but enters BlockedStatus
        # because the backend relation doesn't exist yet.
        _start.side_effect = None
        self.charm.on.start.emit()
        _start.assert_called_once_with("pgbouncer-pgbouncer@0")
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        _start.reset_mock()

        # Testing charm starts the correct amount of pgbouncer instances and enters activestatus if
        # everything's working fine.
        _start.reset_mock()
        _start.side_effect = None
        _has_relation.return_value = True
        self.charm.on.start.emit()
        _start.assert_called_once_with("pgbouncer-pgbouncer@0")
        _render_prom_service.assert_called_once_with()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)
        _start.reset_mock()

    @patch("charms.operator_libs_linux.v1.systemd.service_running")
    @patch("charms.operator_libs_linux.v1.systemd.service_reload")
    @patch("charms.operator_libs_linux.v1.systemd.service_restart")
    @patch("charm.PgBouncerCharm.check_pgb_running")
    def test_reload_pgbouncer(self, _check_pgb_running, _restart, _reload, _running):
        # Reloads if the service is running
        self.charm._reload_pgbouncer()
        _reload.assert_called_once_with("pgbouncer-pgbouncer@0")
        assert not _restart.called
        _check_pgb_running.assert_called_once()
        _restart.reset_mock()
        _reload.reset_mock()
        _check_pgb_running.reset_mock()

        # Restarts if service is not running
        _running.return_value = False
        self.charm._reload_pgbouncer()
        _restart.assert_called_once_with("pgbouncer-pgbouncer@0")
        assert not _reload.called
        _check_pgb_running.assert_called_once()

        # Verify that if systemd is in error, the charm enters blocked status.
        _restart.side_effect = systemd.SystemdError()
        self.charm._reload_pgbouncer()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @patch("charms.operator_libs_linux.v1.systemd.service_running", return_value=False)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=False,
    )
    def test_check_pgb_running(self, _postgres_ready, _running):
        # check fail on postgres not available
        # Testing charm blocks when the pgbouncer services aren't running
        assert not self.charm.check_pgb_running()
        self.assertIsInstance(self.charm.unit.status, BlockedStatus)
        _postgres_ready.return_value = True

        # check fail when services aren't all running
        assert not self.charm.check_pgb_running()
        self.assertIsInstance(self.charm.unit.status, BlockedStatus)
        calls = [call("pgbouncer-pgbouncer@0")]
        _running.assert_has_calls(calls)
        _running.return_value = True

        # check fail when we can't get service status
        _running.side_effect = systemd.SystemdError
        assert not self.charm.check_pgb_running()
        self.assertIsInstance(self.charm.unit.status, BlockedStatus)
        _running.side_effect = None
        _running.reset_mock()

        # otherwise check all services and return activestatus
        assert self.charm.check_pgb_running()
        _running.assert_any_call("pgbouncer-pgbouncer@0")

    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("relations.peers.Peers.app_databag", new_callable=PropertyMock)
    def test_on_config_changed(self, _app_databag, _render):
        self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.harness.set_leader()
        mock_cores = 1
        self.charm._cores = mock_cores
        max_db_connections = 44

        # set config to include pool_mode and max_db_connections
        self.harness.update_config({
            "pool_mode": "transaction",
            "max_db_connections": max_db_connections,
            "listen_port": 6464,
        })

        # _read.return_value is modified on config update, but the object reference is the same.
        _render.assert_called_with(restart=True)

    @patch("charm.snap.SnapCache")
    def test_install_snap_packages(self, _snap_cache):
        _snap_package = _snap_cache.return_value.__getitem__.return_value
        _snap_package.ensure.side_effect = snap.SnapError
        _snap_package.present = False

        # Test for problem with snap update.
        with self.assertRaises(snap.SnapError):
            self.charm._install_snap_packages([("pgbouncer", {"channel": "1/edge"})])
        _snap_cache.return_value.__getitem__.assert_called_once_with("pgbouncer")
        _snap_cache.assert_called_once_with()
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="1/edge")

        # Test with a not found package.
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = snap.SnapNotFoundError
        with self.assertRaises(snap.SnapNotFoundError):
            self.charm._install_snap_packages([("pgbouncer", {"channel": "1/edge"})])
        _snap_cache.return_value.__getitem__.assert_called_once_with("pgbouncer")
        _snap_cache.assert_called_once_with()
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="1/edge")

        # Then test a valid one.
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = None
        self.charm._install_snap_packages([("pgbouncer", {"channel": "1/edge"})])
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("pgbouncer")
        _snap_package.ensure.assert_called_once_with(snap.SnapState.Latest, channel="1/edge")
        _snap_package.hold.assert_not_called()

        # Test revision
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.ensure.side_effect = None
        self.charm._install_snap_packages([
            ("postgresql", {"revision": {platform.machine(): "42"}})
        ])
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_package.ensure.assert_called_once_with(
            snap.SnapState.Latest, revision="42", channel=""
        )
        _snap_package.hold.assert_called_once_with()

        # Test with refresh
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.present = True
        self.charm._install_snap_packages(
            [("postgresql", {"revision": {platform.machine(): "42"}, "channel": "latest/test"})],
            refresh=True,
        )
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_package.ensure.assert_called_once_with(
            snap.SnapState.Latest, revision="42", channel="latest/test"
        )
        _snap_package.hold.assert_called_once_with()

        # Test without refresh
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        self.charm._install_snap_packages([
            ("postgresql", {"revision": {platform.machine(): "42"}})
        ])
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        _snap_package.ensure.assert_not_called()
        _snap_package.hold.assert_not_called()

        # test missing architecture
        _snap_cache.reset_mock()
        _snap_package.reset_mock()
        _snap_package.present = True
        with self.assertRaises(KeyError):
            self.charm._install_snap_packages(
                [("postgresql", {"revision": {"missingarch": "42"}})],
                refresh=True,
            )
        _snap_cache.assert_called_once_with()
        _snap_cache.return_value.__getitem__.assert_called_once_with("postgresql")
        assert not _snap_package.ensure.called
        assert not _snap_package.hold.called

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

    @patch(
        "charm.PgBouncerCharm.conf_auth_file",
        new_callable=PropertyMock,
        return_value="/dev/shm/pgbouncer_test",
    )
    @patch(
        "relations.backend_database.DatabaseRequires.fetch_relation_field",
        return_value="BACKNEND_USER",
    )
    @patch(
        "charm.BackendDatabaseRequires.relation", new_callable=PropertyMock, return_value=Mock()
    )
    @patch(
        "charm.BackendDatabaseRequires.postgres_databag",
        new_callable=PropertyMock,
        return_value={"endpoints": "HOST:PORT", "read-only-endpoints": "HOST2:PORT"},
    )
    @patch("charm.PgBouncerCharm.get_relation_databases")
    @patch("charm.PgBouncerCharm._reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_file")
    def test_render_pgb_config(
        self,
        _render,
        _reload,
        _get_dbs,
        _postgres_databag,
        _backend_rel,
        _,
        __,
    ):
        _get_dbs.return_value = {
            "1": {"name": "first_test", "legacy": True},
            "2": {"name": "second_test", "legacy": False},
        }

        with open("templates/pgb_config.j2") as file:
            template = Template(file.read())
        self.charm.render_pgb_config()
        _reload.assert_called()
        effective_db_connections = 100
        default_pool_size = math.ceil(effective_db_connections / 2)
        min_pool_size = math.ceil(effective_db_connections / 4)
        reserve_pool_size = math.ceil(effective_db_connections / 4)
        auth_file = "/dev/shm/pgbouncer_test"

        expected_databases = {
            "first_test": {
                "host": "HOST",
                "dbname": "first_test",
                "port": "PORT",
                "auth_user": "pgbouncer_auth_BACKNEND_USER",
            },
            "first_test_readonly": {
                "host": "HOST2",
                "dbname": "first_test",
                "port": "PORT",
                "auth_user": "pgbouncer_auth_BACKNEND_USER",
            },
            "second_test": {
                "host": "HOST",
                "dbname": "second_test",
                "port": "PORT",
                "auth_user": "pgbouncer_auth_BACKNEND_USER",
            },
            "second_test_readonly": {
                "host": "HOST2",
                "dbname": "second_test",
                "port": "PORT",
                "auth_user": "pgbouncer_auth_BACKNEND_USER",
            },
        }
        expected_content = template.render(
            databases=expected_databases,
            readonly_databases={},
            peer_id=0,
            peers=range(1),
            base_socket_dir=f"{PGB_RUN_DIR}/pgbouncer/instance_",
            log_file=f"{PGB_LOG_DIR}/pgbouncer/instance_0/pgbouncer.log",
            pid_file="/tmp/pgbouncer/instance_0/pgbouncer.pid",
            listen_addr="127.0.0.1",
            listen_port=6432,
            pool_mode="session",
            max_db_connections=100,
            default_pool_size=default_pool_size,
            min_pool_size=min_pool_size,
            reserve_pool_size=reserve_pool_size,
            admin_user="pgbouncer_admin_pgbouncer",
            stats_user="pgbouncer_stats_pgbouncer",
            auth_type="scram-sha-256",
            auth_query="SELECT username, password FROM pgbouncer_auth_BACKNEND_USER.get_auth($1)",
            auth_file=auth_file,
            enable_tls=False,
        )
        _render.assert_called_once_with(
            f"{PGB_CONF_DIR}/pgbouncer/instance_0/pgbouncer.ini", expected_content, 0o700
        )
        _render.reset_mock()
        _reload.reset_mock()

        # test constant pool sizes with unlimited connections and no ro endpoints
        with self.harness.hooks_disabled():
            self.harness.update_config({
                "max_db_connections": 0,
            })
        expected_databases["first_test_readonly"]["host"] = "HOST"
        expected_databases["second_test_readonly"]["host"] = "HOST"
        expected_databases["*"] = {
            "host": "HOST",
            "port": "PORT",
            "auth_dbname": "first_test",
            "auth_user": "pgbouncer_auth_BACKNEND_USER",
        }
        _get_dbs.return_value["*"] = {"name": "*", "auth_dbname": "first_test"}

        del _postgres_databag.return_value["read-only-endpoints"]

        self.charm.render_pgb_config()

        _reload.assert_called()
        expected_content = template.render(
            databases=expected_databases,
            readonly_databases={},
            peer_id=0,
            peers=range(1),
            base_socket_dir=f"{PGB_RUN_DIR}/pgbouncer/instance_",
            log_file=f"{PGB_LOG_DIR}/pgbouncer/instance_0/pgbouncer.log",
            pid_file="/tmp/pgbouncer/instance_0/pgbouncer.pid",
            listen_addr="127.0.0.1",
            listen_port=6432,
            pool_mode="session",
            max_db_connections=0,
            default_pool_size=20,
            min_pool_size=10,
            reserve_pool_size=10,
            admin_user="pgbouncer_admin_pgbouncer",
            stats_user="pgbouncer_stats_pgbouncer",
            auth_type="scram-sha-256",
            auth_query="SELECT username, password FROM pgbouncer_auth_BACKNEND_USER.get_auth($1)",
            auth_file=auth_file,
            enable_tls=False,
        )
        _render.assert_called_once_with(
            f"{PGB_CONF_DIR}/pgbouncer/instance_0/pgbouncer.ini", expected_content, 0o700
        )

    @patch("charm.Peers.app_databag", new_callable=PropertyMock, return_value={})
    @patch("charm.PgBouncerCharm.get_secret")
    def test_get_relation_databases_legacy_data(self, _get_secret, _):
        """Test that legacy data will be parsed if new one is not set."""
        self.harness.set_leader(False)
        _get_secret.return_value = """
        [databases]
        test_db = host_cfg
        test_db_standby = host_cfg
        other_db = other_cfg
        """
        result = self.charm.get_relation_databases()
        assert result == {
            "1": {"legacy": False, "name": "test_db"},
            "2": {"legacy": False, "name": "other_db"},
        }
        _get_secret.assert_called_once_with("app", "cfg_file")

        # Get empty dict if no config is set
        _get_secret.return_value = None
        assert self.charm.get_relation_databases() == {}

        # Get empty dict if exception
        _get_secret.return_value = 1
        assert self.charm.get_relation_databases() == {}

        # Get empty dict if no databases
        _get_secret.return_value = """
        [other]
        test_db = host_cfg
        test_db_standby = host_cfg
        other_db = other_cfg
        """
        assert self.charm.get_relation_databases() == {}

    @patch("charm.PgBouncerCharm.get_relation_databases", return_value={"some": "values"})
    def test_generate_relation_databases_not_leader(self, _):
        self.harness.set_leader(False)

        assert self.charm.generate_relation_databases() == {}

    @patch("charm.PgBouncerCharm._collect_readonly_dbs")
    @patch("charm.PgBouncerCharm.update_status")
    @patch("charm.Peers.update_leader")
    def test_on_update_status(self, _update_leader, _update_status, _collect_readonly_dbs):
        event = Mock()

        self.charm._on_update_status(event)

        _update_leader.assert_called_once_with()
        _update_status.assert_called_once_with()
        _collect_readonly_dbs.assert_called_once_with()

    @patch(
        "charm.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="auth_user",
    )
    @patch(
        "charm.BackendDatabaseRequires.postgres_databag",
        new_callable=PropertyMock,
        return_value={},
    )
    @patch(
        "charm.BackendDatabaseRequires.relation", new_callable=PropertyMock, return_value=Mock()
    )
    def test_get_readonly_dbs(self, _backend_rel, _postgres_databag, _):
        with self.harness.hooks_disabled():
            self.harness.update_relation_data(
                self.rel_id, self.charm.app.name, {"readonly_dbs": '["includedb"]'}
            )

        # Returns empty if no wildcard
        assert self.charm._get_readonly_dbs({}) == {}

        # Returns empty if no readonly backends
        assert self.charm._get_readonly_dbs({"*": {"name": "*", "auth_dbname": "authdb"}}) == {}

        _postgres_databag.return_value = {
            "endpoints": "HOST:PORT",
            "read-only-endpoints": "HOST2:PORT,HOST3:PORT",
        }
        assert self.charm._get_readonly_dbs({"*": {"name": "*", "auth_dbname": "authdb"}}) == {
            "includedb_readonly": {
                "auth_dbname": "authdb",
                "auth_user": "auth_user",
                "dbname": "includedb",
                "host": "HOST2,HOST3",
                "port": "PORT",
            }
        }

    @patch("charm.BackendDatabaseRequires.postgres")
    @patch(
        "charm.PgBouncerCharm.get_relation_databases", return_value={"1": {"name": "excludeddb"}}
    )
    def test_collect_readonly_dbs(self, _get_relation_databases, _postgres):
        _postgres._connect_to_database().__enter__().cursor().__enter__().fetchall.return_value = (
            ("includeddb",),
            ("excludeddb",),
        )

        # don't collect if not leader
        self.charm._collect_readonly_dbs()
        assert "readonly_dbs" not in self.charm.peers.app_databag

        with self.harness.hooks_disabled():
            self.harness.set_leader()

        self.charm._collect_readonly_dbs()

        assert self.charm.peers.app_databag["readonly_dbs"] == '["includeddb"]'

        # don't fail if no connection
        _postgres._connect_to_database().__enter__().cursor().__enter__().fetchall.return_value = ()
        _postgres._connect_to_database().__enter__.side_effect = psycopg2.Error

        self.charm._collect_readonly_dbs()

        assert self.charm.peers.app_databag["readonly_dbs"] == '["includeddb"]'

    @patch("charm.HaCluster.relation", new_callable=PropertyMock, return_value=True)
    @patch("charm.PgBouncerCharm._is_exposed", new_callable=PropertyMock, return_value=False)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=False,
    )
    @patch("charm.BackendDatabaseRequires.postgres", new_callable=PropertyMock, return_value=None)
    @patch("charm.PgBouncerCharm.check_pgb_running", return_value=True)
    def test_update_status(self, _check_pgb_running, _postgres, _ready, _is_exposed, _ha_relation):
        # Doesn't clear extensions blocking
        self.charm.unit.status = BlockedStatus(EXTENSIONS_BLOCKING_MESSAGE)

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == EXTENSIONS_BLOCKING_MESSAGE

        # Blocks if no backend
        self.charm.unit.status = ActiveStatus()

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert (
            self.charm.unit.status.message == "waiting for backend database relation to initialise"
        )

        # Blocks if backend is not ready
        self.charm.unit.status = ActiveStatus()
        _postgres.return_value = True

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == "backend database relation not ready"

        # Blocks if using hacluster and not exposed
        self.charm.unit.status = ActiveStatus()
        _ready.return_value = True

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == "ha integration used without data-intgrator"

        # Blocks if using hacluster and not set vip
        self.charm.unit.status = ActiveStatus()
        _is_exposed.return_value = True

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == "ha integration used without vip configuration"

        # Blocks if vip is set and not exposed
        self.charm.unit.status = ActiveStatus()
        _is_exposed.return_value = False
        _ha_relation.return_value = False
        with self.harness.hooks_disabled():
            self.harness.update_config({"vip": "1.2.3.4"})

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == "vip configuration without data-intgrator"

        # Unblocks if running check passes
        self.charm.unit.status = BlockedStatus()
        _is_exposed.return_value = True
        _ha_relation.return_value = True

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, ActiveStatus)

        # Keeps status if checks don't pass
        self.charm.unit.status = BlockedStatus()
        _check_pgb_running.return_value = False

        self.charm.update_status()

        assert isinstance(self.charm.unit.status, BlockedStatus)

        # Leader sets vip in unit status
        _check_pgb_running.return_value = True
        with self.harness.hooks_disabled():
            self.harness.set_leader()

        self.charm.update_status()

        assert self.charm.unit.status.message == "VIP: 1.2.3.4"

    @patch("charm.PgBouncerCharm.config", new_callable=PropertyMock, return_value={})
    def test_configuration_check(self, _config):
        assert self.charm.configuration_check()

        _config.side_effect = ValueError
        assert not self.charm.configuration_check()
        assert isinstance(self.charm.unit.status, BlockedStatus)
        assert self.charm.unit.status.message == "Configuration Error. Please check the logs"

    #
    # Secrets
    #

    def test_scope_obj(self):
        assert self.charm._scope_obj("app") == self.charm.framework.model.app
        assert self.charm._scope_obj("unit") == self.charm.framework.model.unit
        assert self.charm._scope_obj("test") is None

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

    @pytest.mark.usefixtures("use_caplog")
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
        with self._caplog.at_level(logging.DEBUG):
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

    def test_on_secret_remove(self):
        with patch("ops.model.Model.juju_version", new_callable=PropertyMock) as _juju_version:
            event = Mock()

            # New juju
            _juju_version.return_value = JujuVersion("3.6.11")
            self.harness.charm._on_secret_remove(event)
            event.remove_revision.assert_called_once_with()
            event.reset_mock()

            # Old juju
            _juju_version.return_value = JujuVersion("3.6.9")
            self.harness.charm._on_secret_remove(event)
            assert not event.remove_revision.called
            event.reset_mock()

            # No secret
            event.secret.label = None
            self.harness.charm._on_secret_remove(event)
            assert not event.remove_revision.called
            event = Mock()


@patch("ops.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
class TestCharmSecrets(unittest.TestCase):
    # Needed to have it applied on the charm __init__ function, where _translate_field_to_secret_key() is called
    @patch("ops.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def setUp(self, _):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.unit = self.harness.charm.unit

        self.rel_id = self.harness.add_relation(PEER_RELATION_NAME, self.charm.app.name)

    @pytest.fixture
    def use_caplog(self, caplog):
        self._caplog = caplog

    @parameterized.expand([("app", "monitoring-password"), ("unit", "csr")])
    def test_get_secret_secrets(self, _, scope, field):
        with self.harness.hooks_disabled():
            self.harness.set_leader()

        assert self.charm.get_secret(scope, field) is None
        self.charm.set_secret(scope, field, "test")
        assert self.charm.get_secret(scope, field) == "test"

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    def test_set_reset_new_secret(self, _, scope, is_leader):
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
    def test_invalid_secret(self, _, scope, is_leader):
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        with self.assertRaises((RelationDataTypeError, TypeError)):
            self.harness.charm.set_secret(scope, "somekey", 1)

        self.harness.charm.set_secret(scope, "somekey", "")
        assert self.harness.charm.get_secret(scope, "somekey") is None

    @pytest.mark.usefixtures("use_caplog")
    def test_delete_existing_password_secrets(self, _):
        """NOTE: currently ops.testing seems to allow for non-leader to remove secrets too!"""
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        self.harness.charm.set_secret("app", "monitoring-password", "somepw")
        self.harness.charm.remove_secret("app", "monitoring-password")
        assert self.harness.charm.get_secret("app", "monitoring-password") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(False)
        self.harness.charm.set_secret("unit", "csr", "somesecret")
        self.harness.charm.remove_secret("unit", "csr")
        assert self.harness.charm.get_secret("unit", "csr") is None

        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        with self._caplog.at_level(logging.DEBUG):
            self.harness.charm.remove_secret("app", "monitoring-password")
            assert (
                "Non-existing secret monitoring-password was attempted to be removed."
                in self._caplog.text
            )

            self.harness.charm.remove_secret("unit", "csr")
            assert "Non-existing secret csr was attempted to be removed." in self._caplog.text

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
    @patch("ops.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_migration_from_databag(self, scope, is_leader, _, __):
        """Check if we're moving on to use secrets when live upgrade from databag to Secrets usage."""
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        # Getting current password
        entity = getattr(self.charm, scope)
        self.harness.update_relation_data(self.rel_id, entity.name, {"monitoring_password": "bla"})
        assert self.harness.charm.get_secret(scope, "monitoring_password") == "bla"

        # Reset new secret
        self.harness.charm.set_secret(scope, "monitoring-password", "blablabla")
        assert self.harness.charm.model.get_secret(label=f"{PEER_RELATION_NAME}.pgbouncer.{scope}")
        assert self.harness.charm.get_secret(scope, "monitoring-password") == "blablabla"
        assert "monitoring-password" not in self.harness.get_relation_data(
            self.rel_id, getattr(self.charm, scope).name
        )

    @parameterized.expand([("app", True), ("unit", True), ("unit", False)])
    @patch("ops.JujuVersion.has_secrets", new_callable=PropertyMock, return_value=True)
    def test_migration_from_single_secret(self, scope, is_leader, _, __):
        """Check if we're moving on to use secrets when live upgrade from databag to Secrets usage."""
        # App has to be leader, unit can be either
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)

        secret = self.harness.charm.app.add_secret({"monitoring-password": "bla"})

        # Getting current password
        entity = getattr(self.charm, scope)
        self.harness.update_relation_data(
            self.rel_id, entity.name, {SECRET_INTERNAL_LABEL: secret.id}
        )
        assert self.harness.charm.get_secret(scope, "monitoring-password") == "bla"

        # Reset new secret
        # Only the leader can set app secret content.
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)
        self.harness.charm.set_secret(scope, "monitoring-password", "blablabla")
        with self.harness.hooks_disabled():
            self.harness.set_leader(is_leader)
        assert self.harness.charm.model.get_secret(label=f"{PEER_RELATION_NAME}.pgbouncer.{scope}")
        assert self.harness.charm.get_secret(scope, "monitoring-password") == "blablabla"
        assert SECRET_INTERNAL_LABEL not in self.harness.get_relation_data(
            self.rel_id, getattr(self.charm, scope).name
        )
