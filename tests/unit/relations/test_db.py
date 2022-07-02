# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from lib.charms.pgbouncer_operator.v0.pgb import DEFAULT_CONFIG, PgbConfig

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

        # method returns early if charm is not leader
        self.db_relation._on_relation_changed(mock_event)
        _read_cfg.assert_not_called()

        # method returns early if charm cfg[databases][pg_master] doesn't exist
        self.harness.set_leader(True)
        self.db_relation._on_relation_changed(mock_event)
        _defer.assert_called_once()
        _defer.reset_mock()

        # method returns early if relation data doesn't contain a database name
        mock_event.relation.data = MagicMock()
        mock_event.relation.data[_get_units.return_value]["database"] = None
        _read_cfg.return_value["databases"]["pg_master"] = {"test": "value"}
        self.db_relation._on_relation_changed(mock_event)
        _defer.assert_called_once()

    @patch("ops.model.Unit.is_leader", return_value=False)
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

        assert False

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_departed(self, _render, _read):
        assert False

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_broken(self, _render, _read):
        assert False
