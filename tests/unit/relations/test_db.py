# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, PropertyMock, patch, sentinel

from charms.pgbouncer_k8s.v0.pgb import parse_dict_to_kv_string
from ops.model import Unit
from ops.testing import Harness

from charm import PgBouncerCharm
from constants import (
    BACKEND_RELATION_NAME,
    DB_ADMIN_RELATION_NAME,
    DB_RELATION_NAME,
    PEER_RELATION_NAME,
)

from ..helpers import patch_network_get


class TestDb(unittest.TestCase):
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.app = self.charm.app.name
        self.unit = self.charm.unit.name
        self.backend = self.charm.backend
        self.db_relation = self.charm.legacy_db_relation
        self.db_admin_relation = self.charm.legacy_db_admin_relation

        # Define a backend relation
        self.backend_rel_id = self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.harness.add_relation_unit(self.backend_rel_id, "postgres/0")

        # Define a db relation
        self.db_rel_id = self.harness.add_relation(DB_RELATION_NAME, "client_app")
        self.harness.add_relation_unit(self.db_rel_id, "client_app/0")

        # Define a db-admin relation
        self.db_admin_rel_id = self.harness.add_relation(DB_ADMIN_RELATION_NAME, "admin_client")
        self.harness.add_relation_unit(self.db_admin_rel_id, "admin_client/0")

        # Define a peer relation
        with patch("charm.PgBouncerCharm.render_pgb_config"):
            self.peers_rel_id = self.harness.add_relation(PEER_RELATION_NAME, "pgbouncer")
            self.harness.add_relation_unit(self.peers_rel_id, self.unit)

    def test_correct_admin_perms_set_in_constructor(self):
        assert self.charm.legacy_db_relation.relation_name == "db"
        assert self.charm.legacy_db_relation.admin is False

        assert self.charm.legacy_db_admin_relation.relation_name == "db-admin"
        assert self.charm.legacy_db_admin_relation.admin is True

    @patch(
        "charm.PgBouncerCharm.client_relations",
        new_callable=PropertyMock,
        return_value=sentinel.client_rels,
    )
    @patch("relations.backend_database.BackendDatabaseRequires.check_backend", return_value=True)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("charms.pgbouncer_k8s.v0.pgb.generate_password", return_value="test_pass")
    @patch("charms.postgresql_k8s.v0.postgresql.PostgreSQL")
    @patch("charms.postgresql_k8s.v0.postgresql.PostgreSQL.create_user")
    @patch("charms.postgresql_k8s.v0.postgresql.PostgreSQL.create_database")
    @patch("relations.backend_database.BackendDatabaseRequires.remove_auth_function")
    @patch("relations.backend_database.BackendDatabaseRequires.initialise_auth_function")
    @patch("charm.PgBouncerCharm.set_relation_databases")
    @patch("charm.PgBouncerCharm.generate_relation_databases")
    def test_on_relation_joined(
        self,
        _gen_rel_dbs,
        _set_rel_dbs,
        _init_auth,
        _remove_auth,
        _create_database,
        _create_user,
        _postgres,
        _gen_pw,
        _backend_pg,
        _check_backend,
        _,
    ):
        self.harness.set_leader(True)

        _gen_rel_dbs.return_value = {}

        mock_event = Mock()
        mock_event.app.name = "external_test_app"
        mock_event.relation.id = 1

        database = "test_db"
        user = "pgbouncer_user_1_None"
        password = _gen_pw.return_value

        _set_rel_dbs.reset_mock()
        relation_data = mock_event.relation.data = {}
        relation_data[self.charm.unit] = {}
        relation_data[self.charm.app] = {}
        relation_data[mock_event.app] = {"database": database}
        relation_data[mock_event.unit] = {"database": database}
        _backend_pg.return_value = _postgres
        _postgres.create_user = _create_user
        _postgres.create_database = _create_database

        _set_rel_dbs.reset_mock()
        self.db_admin_relation._on_relation_joined(mock_event)
        _set_rel_dbs.assert_called_once_with({"1": {"name": "test_db", "legacy": True}})

        _create_user.assert_called_with(user, password, admin=True)
        _create_database.assert_called_with(database, user, client_relations=sentinel.client_rels)
        _init_auth.assert_called_with([database])

        for dbag in [relation_data[self.charm.unit], relation_data[self.charm.app]]:
            assert dbag["database"] == database
            assert dbag["user"] == user
            assert dbag["password"] == password

        # Check admin permissions aren't present when we use db_relation
        _set_rel_dbs.reset_mock()
        self.db_relation._on_relation_joined(mock_event)
        _create_user.assert_called_with(user, password, admin=False)
        _set_rel_dbs.assert_called_once_with({"1": {"name": "test_db", "legacy": True}})

    @patch("relations.backend_database.BackendDatabaseRequires.check_backend", return_value=True)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("relations.db.DbProvides.get_databags", return_value=[{}])
    @patch("relations.db.DbProvides.update_connection_info")
    @patch("relations.db.DbProvides.update_databags")
    @patch("relations.db.DbProvides.get_allowed_units")
    @patch("relations.db.DbProvides.get_allowed_subnets")
    @patch("relations.db.DbProvides._get_state")
    @patch("charm.PgBouncerCharm.render_pgb_config")
    def test_on_relation_changed(
        self,
        _render_pgb_config,
        _get_state,
        _allowed_subnets,
        _allowed_units,
        _update_databags,
        _update_connection_info,
        _get_databags,
        _backend_postgres,
        _check_backend,
    ):
        self.harness.set_leader(True)

        database = "test_db"
        user = "test_user"
        password = "test_pw"
        _get_databags.return_value[0] = {
            "database": database,
            "user": user,
            "password": password,
        }

        # Call the function
        event = Mock()
        self.db_relation._on_relation_changed(event)

        _update_connection_info.assert_called_with(
            event.relation, self.charm.config["listen_port"]
        )
        _update_databags.assert_called_with(
            event.relation,
            {
                "allowed-subnets": _allowed_subnets.return_value,
                "allowed-units": _allowed_units.return_value,
                "version": self.charm.backend.postgres.get_postgresql_version(),
                "host": "localhost",
                "user": user,
                "password": password,
                "database": database,
                "state": _get_state.return_value,
            },
        )
        _render_pgb_config.assert_called_once_with(reload_pgbouncer=True)

    @patch("relations.db.DbProvides.get_databags", return_value=[{}])
    @patch("relations.db.DbProvides.get_external_app")
    @patch("relations.db.DbProvides.update_databags")
    def test_update_connection_info(self, _update_databags, _get_external_app, _get_databags):
        relation = Mock()
        database = "test_db"
        user = "test_user"
        password = "test_pw"
        port = "5555"

        _get_databags.return_value[0] = {
            "database": database,
            "user": user,
            "password": password,
        }

        master_dbconnstr = {
            "host": "localhost",
            "dbname": database,
            "port": port,
            "user": user,
            "password": password,
            "fallback_application_name": _get_external_app().name,
        }

        standby_hostnames = self.charm.peers.units_ips - {self.charm.peers.leader_ip}
        if len(standby_hostnames) > 0:
            standby_hostname = standby_hostnames.pop()
            standby_dbconnstr = dict(master_dbconnstr)
            standby_dbconnstr.update({"host": standby_hostname, "dbname": f"{database}_standby"})

        self.db_relation.update_connection_info(relation, port)
        _update_databags.assert_called_with(
            relation,
            {
                "master": parse_dict_to_kv_string(master_dbconnstr),
                "port": port,
                "host": "localhost",
            },
        )

    @patch("relations.db.DbProvides.get_allowed_units", return_value="test_string")
    def test_on_relation_departed(self, _get_units):
        self.harness.set_leader(True)
        mock_event = Mock()
        mock_event.relation.data = {
            self.charm.app: {"allowed-units": "app"},
            self.charm.unit: {"allowed-units": "unit"},
        }
        self.db_relation._on_relation_departed(mock_event)

        app_databag = mock_event.relation.data[self.charm.app]
        unit_databag = mock_event.relation.data[self.charm.unit]

        expected_app_databag = {"allowed-units": "test_string"}
        expected_unit_databag = {"allowed-units": "test_string"}

        self.assertDictEqual(app_databag, expected_app_databag)
        self.assertDictEqual(unit_databag, expected_unit_databag)

    @patch("relations.backend_database.BackendDatabaseRequires.check_backend", return_value=True)
    @patch("charms.postgresql_k8s.v0.postgresql.PostgreSQL")
    @patch("charms.postgresql_k8s.v0.postgresql.PostgreSQL.delete_user")
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("relations.backend_database.BackendDatabaseRequires.remove_auth_function")
    @patch("charm.PgBouncerCharm.set_relation_databases")
    @patch("charm.PgBouncerCharm.generate_relation_databases")
    def test_on_relation_broken(
        self,
        _gen_rel_dbs,
        _set_rel_dbs,
        _remove_auth,
        _backend_postgres,
        _delete_user,
        _postgres,
        _check_backend,
    ):
        _gen_rel_dbs.return_value = {"42": {"name": "test_db", "legacy": True}}
        self.harness.set_leader(True)
        database = "test_db"
        username = "test_user"
        _backend_postgres.return_value = _postgres
        _postgres.delete_user = _delete_user

        mock_event = Mock()
        databag = {
            "user": username,
            "database": database,
        }
        mock_event.relation.id = 42
        mock_event.relation.data = {}
        mock_event.relation.data[self.charm.unit] = databag
        mock_event.relation.data[self.charm.app] = databag
        self.charm.peers.app_databag[f"db-{mock_event.relation.id}-relation-breaking"] = "true"

        self.db_relation._on_relation_broken(mock_event)

        _delete_user.assert_called_once_with(username)
        _set_rel_dbs.assert_called_once_with({})

    def test_get_allowed_subnets(self):
        rel = self.charm.model.get_relation("db", self.db_rel_id)
        for key in rel.data.keys():
            if isinstance(key, Unit):
                rel.data[key]["egress-subnets"] = "10.0.0.10,10.0.0.11"

        assert "10.0.0.10,10.0.0.11" == self.charm.legacy_db_relation.get_allowed_subnets(rel)

    def test_get_allowed_units(self):
        rel = self.charm.model.get_relation("db", self.db_rel_id)

        assert "client_app/0" == self.charm.legacy_db_relation.get_allowed_units(rel)

    def test_get_external_app(self):
        rel = self.charm.model.get_relation("db", self.db_rel_id)

        assert "client_app" == self.charm.legacy_db_relation.get_external_app(rel).name
