# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_STANDBY_PREFIX
from lib.charms.pgbouncer_operator.v0.pgb import (
    DEFAULT_CONFIG,
    PgbConfig,
    parse_kv_string_to_dict,
)

TEST_UNIT = {
    "master": "host=master port=1 dbname=testdatabase",
    "standbys": "host=standby1 port=1 dbname=testdatabase",
}


class TestDb(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.db_relation = self.charm.legacy_db_relation
        self.db_admin_relation = self.charm.legacy_db_admin_relation

    def test_correct_admin_perms_set_in_constructor(self):
        assert self.charm.legacy_db_relation.relation_name == "db"
        assert self.charm.legacy_db_relation.admin is False

        assert self.charm.legacy_db_admin_relation.relation_name == "db-admin"
        assert self.charm.legacy_db_admin_relation.admin is True

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("ops.charm.EventBase.defer")
    @patch("relations.db.DbProvides.get_external_units", return_value=[MagicMock()])
    def test_on_relation_changed_early_returns(self, _get_units, _defer, _read_cfg):
        """Validate the various cases where we want _on_relation_changed to return early."""
        mock_event = MagicMock()
        mock_event.defer = _defer

        # changed-hook returns early if charm is not leader
        self.db_relation._on_relation_changed(mock_event)
        _read_cfg.assert_not_called()

        # changed-hook returns early if charm cfg[databases][pg_master] doesn't exist
        self.harness.set_leader(True)
        self.db_relation._on_relation_changed(mock_event)
        _defer.assert_called_once()
        _defer.reset_mock()

        # changed-hook returns early if relation data doesn't contain a database name
        mock_event.relation.data = {}
        mock_event.relation.data[self.db_admin_relation.charm.unit] = None
        mock_event.relation.data[self.charm.app] = {"database": None}
        mock_event.relation.data[_get_units.return_value[0]] = {"database": None}

        _read_cfg.return_value["databases"]["pg_master"] = {"test": "value"}
        self.db_relation._on_relation_changed(mock_event)
        _defer.assert_called_once()

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("ops.framework.EventBase.defer")
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_changed(self, _render, _defer_event, _read):
        mock_event = MagicMock()
        self.db_relation._on_relation_changed(mock_event)

        # mock_unit_db = mock_event.relation.data[self.charm.unit]
        # mock_app_db = mock_event.relation.data[self.charm.app]

        # TODO test if databag is and isn't populated
        # TODO test with and without replicas
        # TODO test scaling on both sides of relation, and how it should change config
        # TODO Assert user creation perms change based on self.db_relation.admin

        assert True  # False

    def test_get_postgres_standbys(self):
        cfg = PgbConfig(DEFAULT_CONFIG)
        cfg["databases"]["not_a_standby"] = {"dbname": "not_a_standby"}
        cfg["databases"]["pg_master"] = {"dbname": "pg_master", "host": "test"}
        cfg["databases"][BACKEND_STANDBY_PREFIX] = {
            "dbname": BACKEND_STANDBY_PREFIX,
            "host": "standby_host",
            "port": "standby_port",
        }
        cfg["databases"][f"{BACKEND_STANDBY_PREFIX}0"] = {
            "dbname": f"{BACKEND_STANDBY_PREFIX}0",
            "host": "standby_host",
            "port": "standby_port",
        }
        cfg["databases"][f"not_a_standby{BACKEND_STANDBY_PREFIX}"] = {
            "dbname": f"not_a_standby{BACKEND_STANDBY_PREFIX}",
            "host": "test",
            "port": "port_test",
        }

        app = "app_name"
        db_name = "db_name"
        user = "user"
        pw = "pw"
        standbys = self.db_relation._get_postgres_standbys(cfg, app, db_name, user, pw)

        assert "not_a_standby" not in standbys
        assert "pg_master" not in standbys

        standby_list = standbys.split(",")
        assert len(standby_list) == 2

        for standby in standby_list:
            standby_dict = parse_kv_string_to_dict(standby)
            assert standby_dict.get("dbname") == db_name
            assert standby_dict.get("host") == "standby_host"
            assert standby_dict.get("port") == "standby_port"
            assert standby_dict.get("user") == user
            assert standby_dict.get("password") == pw
            assert standby_dict.get("fallback_application_name") == app

    @patch("relations.db.DbProvides.get_allowed_units", return_value="test_string")
    def test_on_relation_departed(self, _get_units):
        mock_event = MagicMock()
        mock_event.relation.data = {
            self.charm.app: {"allowed-units": "blah"},
            self.charm.unit: {"allowed-units": "blahh"},
        }
        self.db_relation._on_relation_departed(mock_event)

        app_databag = mock_event.relation.data[self.charm.app]
        unit_databag = mock_event.relation.data[self.charm.unit]

        expected_app_databag = {"allowed-units": "test_string"}
        expected_unit_databag = {"allowed-units": "test_string"}

        self.assertDictEqual(app_databag, expected_app_databag)
        self.assertDictEqual(unit_databag, expected_unit_databag)

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm.remove_user")
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_broken(self, _render, _remove_user, _read):
        """Test that all traces of the given app are removed from pgb config, including user."""
        test_dbname = "test_db"
        test_user = "test_user"

        input_cfg = PgbConfig(DEFAULT_CONFIG)
        input_cfg["databases"]["pg_master"] = {"dbname": "pg_master"}
        input_cfg["databases"]["pgb_postgres_standby_0"] = {"dbname": "pgb_postgres_standby_0"}
        input_cfg["databases"]["pgb_postgres_standby_555"] = {"dbname": "pgb_postgres_standby_555"}
        input_cfg["databases"][f"{test_dbname}"] = {"dbname": f"{test_dbname}"}
        input_cfg["databases"][f"{test_dbname}_standby_0"] = {"dbname": f"{test_dbname}_standby_0"}
        input_cfg["databases"][f"{test_dbname}_standby_1"] = {"dbname": f"{test_dbname}_standby_1"}
        _read.return_value = input_cfg

        mock_event = MagicMock()
        app_databag = {
            "user": test_user,
            "database": test_dbname,
        }
        mock_event.relation.data = {}
        mock_event.relation.data[self.charm.app] = app_databag
        self.db_relation._on_relation_broken(mock_event)

        broken_cfg = PgbConfig(_render.call_args[0][0])
        for backend_dbname in ["pg_master", "pgb_postgres_standby_0", "pgb_postgres_standby_555"]:
            assert backend_dbname in broken_cfg["databases"].keys()

        for dbname in [f"{test_dbname}", f"{test_dbname}_standby_0", f"{test_dbname}_standby_1"]:
            assert dbname not in broken_cfg["databases"].keys()

        _remove_user.assert_called_with(test_user, cfg=input_cfg, render_cfg=False)
