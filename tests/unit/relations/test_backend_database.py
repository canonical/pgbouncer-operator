# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, call, patch

from charms.pgbouncer_k8s.v0.pgb import (
    DEFAULT_CONFIG,
    PGB_DIR,
    PgbConfig,
    get_hashed_password,
)
from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_RELATION_NAME, PEER_RELATION_NAME, PGB
from tests.helpers import patch_network_get


@patch_network_get(private_address="1.1.1.1")
class TestBackendDatabaseRelation(unittest.TestCase):
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.unit = self.charm.unit.name
        self.backend = self.charm.backend

        # Define a backend relation
        self.rel_id = self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.harness.add_relation_unit(self.rel_id, "postgres/0")

        # Define a peer relation
        self.peers_rel_id = self.harness.add_relation(PEER_RELATION_NAME, "pgbouncer/0")
        self.harness.add_relation_unit(self.peers_rel_id, self.unit)

    @patch(
        "relations.backend_database.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="user",
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.relation", new_callable=PropertyMock
    )
    @patch("charms.pgbouncer_k8s.v0.pgb.generate_password", return_value="pw")
    @patch("relations.backend_database.BackendDatabaseRequires.initialise_auth_function")
    @patch("charm.PgBouncerCharm.render_file")
    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm.update_postgres_endpoints")
    def test_on_database_created(
        self,
        _update_endpoints,
        _cfg,
        _render,
        _init_auth,
        _gen_pw,
        _relation,
        _postgres,
        _auth_user,
    ):
        self.harness.set_leader()
        pw = _gen_pw.return_value
        postgres = _postgres.return_value
        _relation = MagicMock()
        _relation.data = {}
        _relation.data[self.charm.app] = {}
        _relation.data[self.charm.app]["database"] = PGB

        mock_event = MagicMock()
        mock_event.username = "mock_user"
        self.backend._on_database_created(mock_event)
        hash_pw = get_hashed_password(self.backend.auth_user, pw)

        postgres.create_user.assert_called_with(self.backend.auth_user, hash_pw, admin=True)
        _init_auth.assert_has_calls([call([self.backend.database.database, "postgres"])])

        _render.assert_any_call(
            f"{PGB_DIR}/userlist.txt", f'"{self.backend.auth_user}" "{hash_pw}"', perms=0o700
        )

        cfg = _cfg.return_value
        assert mock_event.username in cfg["pgbouncer"]["admin_users"]
        assert (
            cfg["pgbouncer"]["auth_query"]
            == f"SELECT username, password FROM {self.backend.auth_user}.get_auth($1)"
        )
        assert cfg["pgbouncer"]["auth_file"] == f"{PGB_DIR}/userlist.txt"

        _update_endpoints.assert_called_once()

    @patch_network_get(private_address="1.1.1.1")
    @patch(
        "relations.backend_database.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="user",
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("relations.peers.Peers.remove_user")
    @patch("charm.PgBouncerCharm.update_postgres_endpoints")
    @patch("charm.PgBouncerCharm.update_client_connection_info")
    @patch("relations.backend_database.BackendDatabaseRequires.remove_auth_function")
    def test_relation_departed(
        self,
        _remove_auth,
        _update_conn_info,
        _update_endpoints,
        _remove_user,
        _postgres,
        _auth_user,
    ):
        self.harness.set_leader()
        depart_event = MagicMock()

        depart_event.departing_unit.app = self.charm.app
        self.backend._on_relation_departed(depart_event)
        _update_endpoints.assert_called()
        _update_endpoints.reset_mock()
        _update_conn_info.assert_called()
        _update_conn_info.reset_mock()
        _remove_auth.assert_called()
        _remove_auth.reset_mock()
        _postgres().delete_user.assert_called()
        _remove_user.assert_called()

        # Check departing when we're just scaling down this
        depart_event.departing_unit = self.charm.unit
        self.backend._on_relation_departed(depart_event)
        _update_endpoints.assert_called()
        _update_conn_info.assert_called()
        _remove_auth.assert_not_called()

    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("charm.PgBouncerCharm.read_pgb_config", return_value=PgbConfig(DEFAULT_CONFIG))
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.delete_file")
    def test_relation_broken(self, _delete_file, _render, _cfg, _postgres):
        event = MagicMock()
        self.harness.set_leader()
        self.charm.peers.app_databag[
            f"{BACKEND_RELATION_NAME}-{event.relation.id}-relation-breaking"
        ] = "true"

        postgres = _postgres.return_value
        postgres.user = "test_user"
        cfg = _cfg.return_value
        cfg.add_user(postgres.user, admin=True)
        cfg["pgbouncer"]["auth_user"] = "test"
        cfg["pgbouncer"]["auth_query"] = "test"

        self.backend._on_relation_broken(event)

        assert "test_user" not in cfg["pgbouncer"]
        assert "auth_user" not in cfg["pgbouncer"]
        assert "auth_query" not in cfg["pgbouncer"]

        _render.assert_called_with(cfg)
        _delete_file.assert_called_with(f"{PGB_DIR}/userlist.txt")

    @patch(
        "relations.backend_database.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="user",
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    def test_initialise_auth_function(self, _postgres, _auth_user):
        install_script = open("src/relations/sql/pgbouncer-install.sql", "r").read()
        dbs = ["test-db"]

        self.backend.initialise_auth_function(dbs)

        _postgres.return_value._connect_to_database.assert_called_with(dbs[0])
        conn = _postgres.return_value._connect_to_database().__enter__()
        cursor = conn.cursor().__enter__()
        cursor.execute.assert_called_with(
            install_script.replace("auth_user", self.backend.auth_user)
        )
        conn.close.assert_called()
