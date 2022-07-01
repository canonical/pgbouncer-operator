# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from lib.charms.pgbouncer_operator.v0 import pgb

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

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_changed(self, _render, _read):
        mock_event = MagicMock()
        mock_unit_db = mock_event.relation.data[self.charm.unit]
        mock_app_db = mock_event.relation.data[self.charm.app]
        self.db_relation._on_relation_changed(mock_event)

        # TODO test if databag is and isn't populated
        # TODO test with and without replicas
        # TODO test scaling on both sides of relation, and how it should change config

        assert False

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_departed(self, _render, _read):
        assert False

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_broken(self, _render, _read):
        assert False
