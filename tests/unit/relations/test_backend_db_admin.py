# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from lib.charms.pgbouncer_operator.v0 import pgb
from relations.backend_db_admin import BackendDbAdminRequires


class TestBackendDbAdmin(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.relation = self.harness.charm.legacy_backend_relation

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_relation_changed(self, _render, _read):
        """This test exists to check the basics for how the config is expected to change.

        The integration tests for this relation are a more extensive test of this functionality.
        """
        mock_event = MagicMock()
        mock_event.unit = "mock_unit"
        mock_event.relation.data = {
            "mock_unit": {
                "master": "host=test port=4039 dbname=testdatabase",
                "standbys": "host=test1 port=4039 dbname=testdatabase",
                "state": "master",
            },
        }

        self.relation._on_relation_changed(mock_event)
        expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        _render.assert_called_with(expected_cfg, reload_pgbouncer=True)
        # TODO assert existing config contains standby info

        mock_event.relation.data = {
            "mock_unit": {
                "master": "host=test port=4039 dbname=testdatabase",
                "state": "standalone",
            },
        }

        self.relation._on_relation_changed(mock_event)
        expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        _render.assert_called_with(expected_cfg, reload_pgbouncer=True)
        # TODO assert existing config no longer contains standby info

        assert False

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm._render_service_configs")
    def test_on_backend_db_admin_relation_ended(self, _render, _read):
        """This test exists to check the basics for how the config is expected to change.

        The integration tests for this relation are a more extensive test of this functionality.
        """
        mock_event = MagicMock()
        self.relation._on_relation_changed(mock_event)
        expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        _render.assert_called_with(expected_cfg, reload_pgbouncer=True)

        # TODO
        assert False
