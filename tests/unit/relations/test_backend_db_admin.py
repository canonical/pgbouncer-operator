# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, call, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_STANDBY_PREFIX
from lib.charms.pgbouncer_k8s.v0 import pgb

TEST_UNIT = {
    "master": "host=master port=1 dbname=testdatabase",
    "standbys": "host=standby1 port=1 dbname=testdatabase",
}


class TestBackendDbAdmin(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.relation = self.harness.charm.legacy_backend_relation

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm.add_user")
    @patch("charm.PgBouncerCharm._render_service_configs")
    @patch("relations.backend_db_admin.BackendDbAdminRequires._trigger_db_relations")
    def test_on_relation_changed(self, _trigger_relations, _render, _add_user, _read):
        """This test exists to check the basics for how the config is expected to change.

        The integration tests for this relation are a more extensive test of this functionality.
        """
        mock_event = MagicMock()
        mock_event.unit = "mock_unit"
        mock_event.relation.data = {"mock_unit": deepcopy(TEST_UNIT)}

        self.relation._on_relation_changed(mock_event)

        # get rendered config from _render, and compare it to expected.
        rendered_cfg = _render.call_args[0][0]
        expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        expected_cfg["databases"]["pg_master"] = pgb.parse_kv_string_to_dict(TEST_UNIT["master"])
        expected_cfg["databases"][f"{BACKEND_STANDBY_PREFIX}0"] = pgb.parse_kv_string_to_dict(
            TEST_UNIT["standbys"]
        )

        self.assertEqual(expected_cfg.render(), rendered_cfg.render())

        _trigger_relations.assert_called()
        _trigger_relations.reset_mock()

        del mock_event.relation.data["mock_unit"]["standbys"]

        self.relation._on_relation_changed(mock_event)

        rendered_cfg = _render.call_args[0][0]
        expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        expected_cfg["databases"]["pg_master"] = pgb.parse_kv_string_to_dict(TEST_UNIT["master"])
        self.assertEqual(expected_cfg.render(), rendered_cfg.render())
        # Assert there's no standby information in the rendered config.
        self.assertNotIn(f"{BACKEND_STANDBY_PREFIX}0", rendered_cfg.keys())

        _trigger_relations.assert_called()

    @patch("charm.PgBouncerCharm._read_pgb_config", return_value=pgb.PgbConfig(pgb.DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm.add_user")
    @patch("charm.PgBouncerCharm._render_service_configs")
    @patch("relations.backend_db_admin.BackendDbAdminRequires._trigger_db_relations")
    def test_on_relation_departed(self, _trigger_relations, _render, _add_user, _read):
        """This test exists to check the basics for how the config is expected to change.

        The integration tests for this relation are a more extensive test of this functionality.
        """
        setup_mock_event = MagicMock()
        setup_mock_event.unit = "mock_unit"
        setup_mock_event.relation.data = {"mock_unit": deepcopy(TEST_UNIT)}
        self.relation._on_relation_changed(setup_mock_event)
        setup_cfg = pgb.PgbConfig(_render.call_args[0][0])
        _trigger_relations.reset_mock()

        depart_mock_event = MagicMock()
        depart_mock_event.unit = "mock_unit"
        depart_mock_event.relation.data = {
            "mock_unit": {
                "master": "host=master port=1 dbname=testdatabase",
            }
        }
        self.relation._on_relation_departed(depart_mock_event)
        departed_cfg = pgb.PgbConfig(_render.call_args[0][0])
        self.assertNotEqual(departed_cfg.render(), setup_cfg.render())
        assert list(departed_cfg["databases"].keys()) == ["pg_master"]

        _trigger_relations.assert_called_once()

    @patch("charm.PgBouncerCharm._read_pgb_config")
    @patch("charm.PgBouncerCharm.remove_user")
    @patch("charm.PgBouncerCharm._render_service_configs")
    @patch("relations.backend_db_admin.BackendDbAdminRequires._trigger_db_relations")
    def test_on_relation_broken(self, _trigger_relations, _render, _remove_user, _read):
        input_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        input_cfg["databases"]["pg_master"] = {"test": "value"}
        input_cfg["databases"]["pgb_postgres_standby_0"] = {"test": "value"}
        input_cfg["databases"]["pgb_postgres_standby_555"] = {"test": "value"}
        input_cfg["databases"]["other_database"] = {"test": "value"}
        _read.return_value = input_cfg

        self.relation._on_relation_broken(MagicMock())

        broken_cfg = pgb.PgbConfig(_render.call_args[0][0])
        for dbname in ["pg_master", "pgb_postgres_standby_0", "pgb_postgres_standby_555"]:
            assert dbname not in broken_cfg["databases"].keys()
        assert "other_database" in broken_cfg["databases"].keys()

        _remove_user.assert_called_with("jujuadmin_pgbouncer")
        _trigger_relations.assert_called_once()

    @patch("ops.framework.BoundEvent.emit")
    @patch("ops.model.Model.get_relation")
    def test_trigger_db_relations(self, _get_relation, _emit_relation_changed):
        _get_relation.return_value = None
        self.relation._trigger_db_relations()
        _emit_relation_changed.assert_not_called()

        _get_relation.return_value = "Not None"
        self.relation._trigger_db_relations()
        _emit_relation_changed.assert_has_calls([call("Not None"), call("Not None")])
