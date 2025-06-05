# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres client relation hooks & helpers.

Importantly, this relation doesn't handle scaling the same way others do. All PgBouncer nodes are
read/writes, and they expose the read/write nodes of the backend database through the database name
f"{dbname}_readonly".

┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ relation (id: 4) ┃ application                                         ┃ pgbouncer                                            ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ relation name    │ first-database                                      │ database                                             │
│ interface        │ postgresql_client                                   │ postgresql_client                                    │
│ leader unit      │ 0                                                   │ 1                                                    │
├──────────────────┼─────────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ application data │ ╭─────────────────────────────────────────────────╮ │ ╭──────────────────────────────────────────────────╮ │
│                  │ │                                                 │ │ │                                                  │ │
│                  │ │  data              {"endpoints":                │ │ │  data                 {"database":               │ │
│                  │ │                    "10.180.162.135:6432",       │ │ │                       "application_first_datab…  │ │
│                  │ │                    "password":                  │ │ │                       "extra-user-roles":        │ │
│                  │ │                    "Zw6WZEgvDvZIAh5fk0tGlRYE",  │ │ │                       "CREATEDB,CREATEROLE"}     │ │
│                  │ │                    "read-only-endpoints":       │ │ │  endpoints            10.180.162.135:6432        │ │
│                  │ │                    "10.180.162.135:6432",       │ │ │  password             Zw6WZEgvDvZIAh5fk0tGlRYE   │ │
│                  │ │                    "username":                  │ │ │  read-only-endpoints  10.180.162.135:6432        │ │
│                  │ │                    "relation_id_4", "version":  │ │ │  username             relation_id_4              │ │
│                  │ │                    "12.12"}                     │ │ │  version              12.12                      │ │
│                  │ │  database          application_first_database   │ │ ╰──────────────────────────────────────────────────╯ │
│                  │ │  extra-user-roles  CREATEDB,CREATEROLE          │ │                                                      │
│                  │ ╰─────────────────────────────────────────────────╯ │                                                      │
│ unit data        │ ╭─ application/0* ─╮                                │ ╭─ pgbouncer/1* ─╮ ╭─ pgbouncer/2 ─╮                 │
│                  │ │ <empty>          │                                │ │ <empty>        │ │ <empty>       │                 │
│                  │ ╰──────────────────╯                                │ ╰────────────────╯ ╰───────────────╯                 │
└──────────────────┴─────────────────────────────────────────────────────┴──────────────────────────────────────────────────────┘

"""

import logging
from hashlib import shake_128
from typing import List, Optional
from urllib.parse import quote

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseProvides,
    DatabaseRequestedEvent,
)
from charms.pgbouncer_k8s.v0 import pgb
from charms.postgresql_k8s.v0.postgresql import PERMISSIONS_GROUP_ADMIN
from charms.postgresql_k8s.v1.postgresql import (
    PostgreSQLCreateDatabaseError,
    PostgreSQLCreateUserError,
    PostgreSQLDeleteUserError,
    PostgreSQLGetPostgreSQLVersionError,
)
from ops import (
    Application,
    BlockedStatus,
    CharmBase,
    MaintenanceStatus,
    Object,
    Relation,
    RelationBrokenEvent,
    RelationDepartedEvent,
)

from constants import CLIENT_RELATION_NAME, PGB_RUN_DIR

logger = logging.getLogger(__name__)


class PgBouncerProvider(Object):
    """Defines functionality for the 'provides' side of the 'postgresql-client' relation.

    Hook events observed:
        - database-requested
        - relation-broken
    """

    def __init__(self, charm: CharmBase, relation_name: str = CLIENT_RELATION_NAME) -> None:
        """Constructor for PgbouncerProvider object.

        Args:
            charm: the charm for which this relation is provided
            relation_name: the name of the relation
        """
        super().__init__(charm, relation_name)

        self.charm = charm
        self.relation_name = relation_name
        self.database_provides = DatabaseProvides(self.charm, relation_name=self.relation_name)

        self.framework.observe(
            self.database_provides.on.database_requested, self._on_database_requested
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed, self._on_relation_departed
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_broken, self._on_relation_broken
        )

    @staticmethod
    def sanitize_extra_roles(extra_roles: Optional[str]) -> List[str]:
        """Standardize and sanitize user extra-roles."""
        if extra_roles is None:
            return []

        return [role.lower() for role in extra_roles.split(",")]

    def _depart_flag(self, relation):
        return f"{self.relation_name}_{relation.id}_departing"

    def _unit_departing(self, relation):
        return self.charm.peers.unit_databag.get(self._depart_flag(relation), None) == "true"

    def _on_database_requested(self, event: DatabaseRequestedEvent) -> None:
        """Handle the client relation-requested event.

        Generate password and handle user and database creation for the related application.

        Deferrals:
            - If backend relation is not fully initialised
        """
        rel_id = event.relation.id
        self.database_provides.set_subordinated(rel_id)

        if not self.charm.backend.check_backend():
            event.defer()
            return

        for key in self.charm.peers.relation.data:
            if (
                key != self.charm.app
                and self.charm.peers.relation.data[key].get("auth_file_set", "false") != "true"
            ):
                logger.debug("Backend credentials not yet set on all units")
                event.defer()
                return

        # Retrieve the database name and extra user roles using the charm library.
        database = event.database

        # Make sure that certain groups are not in the list
        extra_user_roles = self.sanitize_extra_roles(event.extra_user_roles)

        dbs = self.charm.generate_relation_databases()
        dbs[str(rel_id)] = {"name": database, "legacy": False}
        if (
            PERMISSIONS_GROUP_ADMIN in extra_user_roles
            or "superuser" in extra_user_roles
            or "createdb" in extra_user_roles
            or "charmed_dba" in extra_user_roles
            or "charmed_dml" in extra_user_roles
            or "charmed_read" in extra_user_roles
            or "charmed_stats" in extra_user_roles
        ):
            dbs["*"] = {"name": "*", "auth_dbname": database}

        self.charm.set_relation_databases(dbs)

        pgb_dbs_hash = shake_128(
            self.charm.peers.app_databag["pgb_dbs_config"].encode()
        ).hexdigest(16)
        for key in self.charm.peers.relation.data:
            # We skip the leader so we don't have to wait on the defer
            if (
                key != self.charm.app
                and key != self.charm.unit
                and self.charm.peers.relation.data[key].get("pgb_dbs", "") != pgb_dbs_hash
            ):
                logger.debug("Not all units have synced configuration")
                event.defer()
                return

        # Creates the user and the database for this specific relation.
        user = f"relation_id_{rel_id}"
        logger.debug("generating relation user")
        password = pgb.generate_password()
        try:
            self.charm.backend.postgres.create_user(
                user, password, extra_user_roles=extra_user_roles
            )
            logger.debug("creating database")
            self.charm.backend.postgres.create_database(
                database, user, client_relations=self.charm.client_relations
            )
            # set up auth function
            self.charm.backend.remove_auth_function(dbs=[database])
            self.charm.backend.initialise_auth_function(dbs=[database])
        except (
            PostgreSQLCreateDatabaseError,
            PostgreSQLCreateUserError,
            PostgreSQLGetPostgreSQLVersionError,
        ) as e:
            logger.exception(e)
            self.charm.unit.status = BlockedStatus(
                f"Failed to initialize {self.relation_name} relation"
            )
            return

        self.charm.render_pgb_config()
        self.set_ready()

        # Share the credentials and updated connection info with the client application.
        self.database_provides.set_credentials(rel_id, user, password)
        # Set the database name
        self.database_provides.set_database(rel_id, database)
        self.update_connection_info(event.relation)

    def _on_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Check if this relation is being removed, and update databags accordingly.

        If the leader is being removed, we check if this unit is departing. This occurs only on
        relation deletion, so we set a flag for the relation-broken hook to remove the relation.
        When scaling down, we don't set this flag and we just let the newly elected leader take
        control of the pgbouncer config.
        """
        self.update_connection_info(event.relation)

        # This only ever evaluates to true when the relation is being removed - on app scale-down,
        # depart events are only sent to the other application in the relation.
        if event.departing_unit == self.charm.unit:
            self.charm.peers.unit_databag.update({self._depart_flag(event.relation): "true"})

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Remove the user created for this relation, and revoke connection permissions."""
        self.update_connection_info(event.relation)
        if not self.charm.backend.check_backend() or not self.charm.unit.is_leader():
            return

        if self._unit_departing(event.relation):
            # This unit is being removed, so don't update the relation.
            self.charm.peers.unit_databag.pop(self._depart_flag(event.relation), None)
            return

        dbs = self.charm.get_relation_databases()
        database = dbs.pop(str(event.relation.id), {}).get("name")
        self.charm.set_relation_databases(dbs)

        # Delete the user.
        try:
            user = f"relation_id_{event.relation.id}"
            self.charm.backend.postgres.delete_user(user)
            delete_db = database not in [db.get("name") for db in dbs.values()]
            if database and delete_db:
                self.charm.backend.remove_auth_function(dbs=[database])
        except PostgreSQLDeleteUserError as e:
            logger.exception(e)
            self.charm.unit.status = BlockedStatus(
                f"Failed to delete user during {self.relation_name} relation broken event"
            )
            raise

    def update_connection_info(self, relation):
        """Updates client-facing relation information."""
        if not self.charm.unit.is_leader() or not self.charm.configuration_check():
            return

        # Set the read/write endpoint.
        rel_data = self.database_provides.fetch_relation_data(
            [relation.id], ["external-node-connectivity", "database"]
        ).get(relation.id, {})
        exposed = bool(rel_data.get("external-node-connectivity", False))
        database = rel_data.get("database")
        user = f"relation_id_{relation.id}"
        password = self.database_provides.fetch_my_relation_field(relation.id, "password")
        if not database or not password:
            return

        if exposed:
            if self.charm.config.vip:
                host = str(self.charm.config.vip)
                uri_host = host
            else:
                host = self.charm.peers.leader_ip
                uri_host = ",".join([
                    self.charm.peers.leader_ip,
                    *[ip for ip in self.charm.peers.units_ips if ip != self.charm.peers.leader_ip],
                ])
        elif self.charm.config.local_connection_type == "uds":
            host = f"{PGB_RUN_DIR}/{self.charm.app.name}/instance_0"
            uri_host = host
        else:
            host = "localhost"
            uri_host = host

        port = self.charm.config.listen_port

        initial_status = self.charm.unit.status
        self.charm.unit.status = MaintenanceStatus(
            f"Updating {self.relation_name} relation connection information"
        )
        rw_endpoint = f"{host}:{port}"
        self.database_provides.set_endpoints(
            relation.id,
            rw_endpoint,
        )
        # Set connection string URI.
        self.database_provides.set_uris(
            relation.id,
            f"postgresql://{user}:{password}@{quote(uri_host, safe=',')}:{port}/{database}",
        )
        self.update_read_only_endpoints(relation, user, password, database)

        # Set the database version.
        if self.charm.backend.check_backend():
            self.database_provides.set_version(
                relation.id, self.charm.backend.postgres.get_postgresql_version(current_host=False)
            )

        self.charm.unit.status = initial_status
        self.charm.update_status()

    def set_ready(self) -> None:
        """Marks the unit as ready for all database relations."""
        for relation in self.model.relations[self.relation_name]:
            relation.data[self.charm.unit].update({"state": "ready"})

    def update_read_only_endpoints(
        self,
        relation: Optional[Relation] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        """Set the read-only endpoint only if there are replicas."""
        if not self.charm.unit.is_leader():
            return

        # Get the current relation or all the relations if this is triggered by another type of
        # event.
        relations = [relation] if relation else self.model.relations[self.relation_name]
        if not relation:
            user = None
            password = None
            database = None

        port = self.charm.config.listen_port
        ips = self.charm.peers.units_ips
        ips.discard(self.charm.peers.leader_ip)
        ips = list(ips)
        ips.sort()

        exposed_read_only_endpoints = (
            ",".join(f"{x}:{port}" for x in ips)
            if len(ips) > 0
            else f"{self.charm.peers.leader_ip}:{port}"
        )
        exposed_read_only_hosts = (
            ",".join([*ips, self.charm.peers.leader_ip])
            if len(ips) > 0
            else f"{self.charm.peers.leader_ip}"
        )

        for relation in relations:
            if not user or not password or not database:
                user = f"relation_id_{relation.id}"
                database = self.database_provides.fetch_relation_field(relation.id, "database")
                password = self.database_provides.fetch_my_relation_field(relation.id, "password")

            if bool(
                self.database_provides.fetch_relation_field(
                    relation.id, "external-node-connectivity"
                )
            ):
                if self.charm.config.vip:
                    self.database_provides.set_read_only_endpoints(
                        relation.id, f"{self.charm.config.vip}:{port}"
                    )
                    read_only_uri = f"postgresql://{user}:{password}@{self.charm.config.vip}:{port}/{database}_readonly"
                else:
                    self.database_provides.set_read_only_endpoints(
                        relation.id, exposed_read_only_endpoints
                    )
                    read_only_uri = f"postgresql://{user}:{password}@{exposed_read_only_hosts}:{port}/{database}_readonly"
            else:
                if self.charm.config.local_connection_type == "uds":
                    host = f"{PGB_RUN_DIR}/{self.charm.app.name}/instance_0"
                else:
                    host = "localhost"
                self.database_provides.set_read_only_endpoints(relation.id, f"{host}:{port}")
                read_only_uri = f"postgresql://{user}:{password}@{quote(host, safe=',')}:{port}/{database}_readonly"
            # Make sure that the URI will be a secret
            if (
                secret_fields := self.database_provides.fetch_relation_field(
                    relation.id, "requested-secrets"
                )
            ) and "read-only-uris" in secret_fields:
                self.database_provides.set_read_only_uris(relation.id, read_only_uri)
            # Reset the creds for the next iteration
            user = None
            password = None
            database = None

    def get_external_app(self, relation):
        """Gets external application, as an Application object.

        TODO this is stolen from the db relation - cleanup
        """
        for entry in relation.data:
            if isinstance(entry, Application) and entry != self.charm.app:
                return entry
