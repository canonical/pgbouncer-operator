# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, call, patch

from charms.pgbouncer_k8s.v0.pgb import get_hashed_password
from ops.model import WaitingStatus
from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_RELATION_NAME, PEER_RELATION_NAME, PGB_CONF_DIR
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
        with patch("charm.PgBouncerCharm.render_pgb_config"):
            self.peers_rel_id = self.harness.add_relation(PEER_RELATION_NAME, "pgbouncer/0")
            self.harness.add_relation_unit(self.peers_rel_id, self.unit)

    @patch("charm.PgBouncerCharm.get_secret", return_value=None)
    @patch("charm.PgBouncerCharm.render_prometheus_service")
    @patch("relations.peers.Peers.app_databag", new_callable=PropertyMock)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.stats_user",
        new_callable=PropertyMock,
        return_value="stats_user",
    )
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
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.render_auth_file")
    def test_on_database_created(
        self,
        _render_auth_file,
        _render_cfg_file,
        _init_auth,
        _gen_pw,
        _relation,
        _postgres,
        _auth_user,
        _stats_user,
        _app_databag,
        _render_prometheus_service,
        _,
    ):
        self.harness.set_leader(True)
        pw = _gen_pw.return_value
        postgres = _postgres.return_value
        _relation.return_value.data = {}
        _relation.return_value.data[self.charm.app] = {"database": "database"}

        mock_event = MagicMock()
        mock_event.username = "mock_user"
        self.backend._on_database_created(mock_event)
        hash_pw = get_hashed_password(self.backend.auth_user, pw)

        postgres.create_user.assert_called_with(self.backend.auth_user, hash_pw, admin=True)
        _init_auth.assert_has_calls([call([self.backend.database.database, "postgres"])])

        hash_mon_pw = get_hashed_password(self.backend.stats_user, pw)
        _render_auth_file.assert_any_call(
            f'"{self.backend.auth_user}" "{hash_pw}"\n"{self.backend.stats_user}" "{hash_mon_pw}"'
        )

        _render_prometheus_service.assert_called_with()
        _render_cfg_file.assert_called_once_with(reload_pgbouncer=True)

    @patch("charm.PgBouncerCharm.render_prometheus_service")
    @patch("charm.PgBouncerCharm.render_auth_file")
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.get_secret")
    def test_on_database_created_not_leader(
        self, _get_secret, _render_pgb, _render_auth, _render_prometheus_service
    ):
        self.harness.set_leader(False)

        # No secret yet
        _get_secret.return_value = None

        mock_event = MagicMock()
        mock_event.username = "mock_user"
        self.backend._on_database_created(mock_event)

        assert not _render_auth.called
        assert not _render_pgb.called
        _get_secret.assert_called_once_with("app", "auth_file")
        mock_event.defer.assert_called_once_with()

        _get_secret.return_value = "AUTH"
        self.backend._on_database_created(mock_event)
        _render_auth.assert_called_once_with("AUTH")
        _render_prometheus_service.assert_called_with()
        _render_pgb.assert_called_once_with(reload_pgbouncer=True)

    @patch("charm.PgBouncerCharm.update_client_connection_info")
    @patch("charm.PgBouncerCharm.render_pgb_config")
    def test_on_endpoints_changed(self, _render_pgb, _update_client_conn):
        self.harness.set_leader()
        _update_client_conn.reset_mock()

        self.charm.backend._on_endpoints_changed(MagicMock())

        _render_pgb.assert_called_once_with(reload_pgbouncer=True)
        _update_client_conn.assert_called_once_with()

    @patch("charm.PgBouncerCharm.update_client_connection_info")
    @patch("charm.PgBouncerCharm.render_pgb_config")
    def test_on_relation_changed(self, _render_pgb, _update_client_conn):
        self.harness.set_leader()
        _update_client_conn.reset_mock()

        self.charm.backend._on_relation_changed(MagicMock())

        _render_pgb.assert_called_once_with(reload_pgbouncer=True)
        _update_client_conn.assert_called_once_with()
        _render_pgb.reset_mock()
        _update_client_conn.reset_mock()

    @patch_network_get(private_address="1.1.1.1")
    @patch(
        "relations.backend_database.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="user",
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("charm.PgBouncerCharm.render_pgb_config")
    def test_relation_departed(self, _render, _postgres, _auth_user):
        self.harness.set_leader(True)
        depart_event = MagicMock()
        depart_event.departing_unit = self.charm.unit
        self.backend._on_relation_departed(depart_event)
        _render.assert_called_once_with(reload_pgbouncer=True)

    @patch("charm.PgBouncerCharm.remove_exporter_service")
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.delete_file")
    def test_relation_broken(self, _delete_file, _render, _postgres, _remove_exporter):
        event = MagicMock()
        self.harness.set_leader()
        self.charm.peers.app_databag[
            f"{BACKEND_RELATION_NAME}-{event.relation.id}-relation-breaking"
        ] = "true"

        postgres = _postgres.return_value
        postgres.user = "test_user"

        self.backend._on_relation_broken(event)

        _render.assert_called_once_with(reload_pgbouncer=True)
        _delete_file.assert_called_with(f"{PGB_CONF_DIR}/pgbouncer/userlist.txt")
        _remove_exporter.assert_called_once_with()

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

    @patch(
        "relations.backend_database.BackendDatabaseRequires.ready",
        new_callable=PropertyMock,
        return_value=True,
    )
    def test_check_backend(self, _ready):
        assert self.charm.backend.check_backend()

        _ready.return_value = False
        assert not self.charm.backend.check_backend()
        assert isinstance(self.charm.unit.status, WaitingStatus)
