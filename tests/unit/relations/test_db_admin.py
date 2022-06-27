# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from lib.charms.pgbouncer_operator.v0 import pgb

TEST_UNIT = {
    "master": "host=master port=1 dbname=testdatabase",
    "standbys": "host=standby1 port=1 dbname=testdatabase",
}


class TestBackendDbAdmin(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.relation = self.harness.charm.legacy_db_admin_relation

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_changed(self, _render, _read):
        pass

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_departed(self, _render, _read):
        pass
