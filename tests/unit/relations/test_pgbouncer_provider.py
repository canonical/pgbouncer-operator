# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, PropertyMock, patch, sentinel

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import (
    BACKEND_RELATION_NAME,
    CLIENT_RELATION_NAME,
    PEER_RELATION_NAME,
)


class TestPgbouncerProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.app = self.charm.app.name
        self.unit = self.charm.unit.name
        self.backend = self.charm.backend
        self.client_relation = self.charm.client_relation

        # Define a peer relation
        with patch("charm.PgBouncerCharm.render_pgb_config"):
            self.peers_rel_id = self.harness.add_relation(PEER_RELATION_NAME, "pgbouncer")
            self.harness.add_relation_unit(self.peers_rel_id, self.unit)

        # Define a backend relation
        self.backend_rel_id = self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.harness.add_relation_unit(self.backend_rel_id, "postgres/0")

        # Define a pgbouncer provider relation
        self.client_rel_id = self.harness.add_relation(CLIENT_RELATION_NAME, "application")
        self.harness.add_relation_unit(self.client_rel_id, "application/0")

    @patch(
        "charm.PgBouncerCharm.client_relations",
        new_callable=PropertyMock,
        return_value=sentinel.client_rels,
    )
    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("relations.backend_database.BackendDatabaseRequires.check_backend", return_value=True)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres_databag",
        new_callable=PropertyMock,
        return_value={"endpoints": "test:endpoint"},
    )
    @patch(
        "relations.backend_database.BackendDatabaseRequires.auth_user",
        new_callable=PropertyMock,
        return_value="test_auth_user",
    )
    @patch("charms.pgbouncer_k8s.v0.pgb.generate_password", return_value="test_pass")
    @patch("relations.pgbouncer_provider.PgBouncerProvider.update_read_only_endpoints")
    @patch("relations.pgbouncer_provider.PgBouncerProvider.get_database", return_value="test-db")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_credentials")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_endpoints")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_version")
    @patch(
        "charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.fetch_my_relation_field",
        return_value="test_pass",
    )
    @patch("charm.PgBouncerCharm.set_relation_databases")
    @patch("charm.PgBouncerCharm.generate_relation_databases")
    def test_on_database_requested(
        self,
        _gen_rel_dbs,
        _set_rel_dbs,
        _dbp_fetch_my_relation_field,
        _dbp_set_version,
        _dbp_set_endpoints,
        _dbp_set_credentials,
        _get_database,
        _update_read_only_endpoints,
        _password,
        _auth_user,
        _pg_databag,
        _pg,
        _check_backend,
        _render_pgb_config,
        _,
    ):
        self.harness.set_leader()
        _gen_rel_dbs.return_value = {}

        event = MagicMock()
        rel_id = event.relation.id = self.client_rel_id
        database = event.database = "test-db"
        event.extra_user_roles = "SUPERUSER"
        event.external_node_connectivity = False
        user = f"relation_id_{rel_id}"
        with self.harness.hooks_disabled():
            self.harness.update_relation_data(rel_id, "application", {"database": "test-db"})

        # check we exit immediately if backend doesn't exist.
        _check_backend.return_value = False
        self.client_relation._on_database_requested(event)
        _pg.create_user.assert_not_called()

        # check we exit immediately if not all units are set.
        _check_backend.return_value = True
        self.client_relation._on_database_requested(event)
        _pg.create_user.assert_not_called()

        with self.harness.hooks_disabled():
            self.harness.update_relation_data(
                self.peers_rel_id, self.unit, {"auth_file_set": "true"}
            )
            self.harness.update_relation_data(
                self.peers_rel_id, self.app, {"pgb_dbs_config": "{}"}
            )
        self.client_relation._on_database_requested(event)

        # Verify we've called everything we should
        _pg().create_user.assert_called_with(
            user, _password(), extra_user_roles=event.extra_user_roles
        )
        _pg().create_database.assert_called_with(
            database, user, client_relations=sentinel.client_rels
        )
        _dbp_set_credentials.assert_called_with(rel_id, user, _password())
        _dbp_set_version.assert_called_with(rel_id, _pg().get_postgresql_version())
        _dbp_set_endpoints.assert_called_with(
            rel_id, f"localhost:{self.charm.config['listen_port']}"
        )
        _set_rel_dbs.assert_called_once_with({
            str(rel_id): {"name": "test-db", "legacy": False},
            "*": {"name": "*", "auth_dbname": "test-db"},
        })
        _render_pgb_config.assert_called_once_with(reload_pgbouncer=True)

    @patch("relations.backend_database.BackendDatabaseRequires.check_backend", return_value=True)
    @patch(
        "relations.backend_database.BackendDatabaseRequires.postgres", new_callable=PropertyMock
    )
    @patch("charm.PgBouncerCharm.set_relation_databases")
    @patch("charm.PgBouncerCharm.generate_relation_databases")
    def test_on_relation_broken(self, _gen_rel_dbs, _set_rel_dbs, _pg, _check_backend):
        _pg.return_value.get_postgresql_version.return_value = "10"
        _gen_rel_dbs.return_value = {"1": {"name": "test_db", "legacy": False}}
        self.harness.set_leader()

        event = MagicMock()
        rel_id = event.relation.id = 1
        external_app = self.charm.client_relation.get_external_app(event.relation)
        event.relation.data = {external_app: {"database": "test_db"}}
        user = f"relation_id_{rel_id}"

        self.client_relation._on_relation_broken(event)
        _pg().delete_user.assert_called_with(user)

        _set_rel_dbs.assert_called_once_with({})

    @patch(
        "charm.Peers.units_ips",
        new_callable=PropertyMock,
        return_value={"192.0.2.0", "192.0.2.1"},
    )
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.fetch_my_relation_field")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.fetch_relation_data")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_read_only_uris")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_uris")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_read_only_endpoints")
    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseProvides.set_endpoints")
    def test_update_connection_info(
        self,
        _set_endpoints,
        _set_ro_endpoints,
        _set_uris,
        _set_read_only_uris,
        _fetch_relation_data,
        _fetch_my_relation_field,
        _,
    ):
        self.harness.set_leader(False)
        _fetch_relation_data.return_value = {
            self.client_rel_id: {
                "database": "test_db",
                "external-node-connectivity": False,
            }
        }
        _fetch_my_relation_field.return_value = "test_password"
        rel = self.charm.model.get_relation("db", self.client_rel_id)

        # Early exit if not leader
        self.client_relation.update_connection_info(rel)

        assert not _set_endpoints.called

        # Test local connection
        self.harness.set_leader(True)
        self.client_relation.update_connection_info(rel)

        _set_endpoints.assert_called_once_with(self.client_rel_id, "localhost:6432")
        _set_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@localhost:6432/test_db",
        )
        _set_read_only_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@localhost:6432/test_db_readonly",
        )
        _set_ro_endpoints.assert_called_once_with(self.client_rel_id, "localhost:6432")
        _set_endpoints.reset_mock()
        _set_uris.reset_mock()
        _set_read_only_uris.reset_mock()
        _set_ro_endpoints.reset_mock()

        # Test exposed connection without vip
        _fetch_relation_data.return_value[self.client_rel_id]["external-node-connectivity"] = True

        self.client_relation.update_connection_info(rel)

        _set_endpoints.assert_called_once_with(self.client_rel_id, "192.0.2.0:6432")
        _set_ro_endpoints.assert_called_once_with(self.client_rel_id, "192.0.2.1:6432")
        _set_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@192.0.2.0,192.0.2.1:6432/test_db",
        )
        _set_read_only_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@192.0.2.1,192.0.2.0:6432/test_db_readonly",
        )
        _set_endpoints.reset_mock()
        _set_ro_endpoints.reset_mock()
        _set_uris.reset_mock()
        _set_read_only_uris.reset_mock()

        # Test exposed connection with vip
        self.harness.update_config({"vip": "1.2.3.4"})

        self.client_relation.update_connection_info(rel)

        _set_endpoints.assert_called_once_with(self.client_rel_id, "1.2.3.4:6432")
        _set_ro_endpoints.assert_called_once_with(self.client_rel_id, "192.0.2.1:6432")
        _set_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@1.2.3.4:6432/test_db",
        )
        _set_read_only_uris.assert_called_once_with(
            self.client_rel_id,
            f"postgresql://relation_id_{self.client_rel_id}:test_password@192.0.2.1,192.0.2.0:6432/test_db_readonly",
        )
        _set_endpoints.reset_mock()
        _set_ro_endpoints.reset_mock()
        _set_uris.reset_mock()
        _set_read_only_uris.reset_mock()
