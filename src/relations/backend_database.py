# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pgbouncer backend-database relation hooks & helpers.

This relation expects that usernames and passwords are generated and provided by the PostgreSQL
charm.

Some example relation data is below. The only parts of this we actually need are the "endpoints"
and "read-only-endpoints" fields. All values are examples taken from a test deployment, and are
not definite.

Example:
-----------------------------------------------------------------------------------------------------------------
┃ relation (id: 3) ┃ postgresql                               ┃ pgbouncer                                       ┃
-----------------------------------------------------------------------------------------------------------------
│ relation name    │ database                                 │ backend-database                                │
│ interface        │ postgresql_client                        │ postgresql_client                               │
│ leader unit      │ 0                                        │ 2                                               │
-----------------------------------------------------------------------------------------------------------------
│ application data │ ╭──────────────────────────────────────╮ │ ╭─────────────────────────────────────────────╮ │
│                  │ │                                      │ │ │                                             │ │
│                  │ │  data       {"database": "pgbouncer",│ │ │  database          pgbouncer                │ │
│                  │ │             "extra-user-roles":      │ │ │  extra-user-roles  SUPERUSER                │ │
│                  │ │             "SUPERUSER"}             │ │ ╰─────────────────────────────────────────────╯ │
│                  │ │  endpoints  10.180.162.236:5432      │ │                                                 │
│                  │ │  password   yPEgUWCYX0SBxpvC         │ │                                                 │
│                  │ │  username   relation-3               │ │                                                 │
│                  │ │  version    12.12                    │ │                                                 │
│                  │ ╰──────────────────────────────────────╯ │                                                 │
│ unit data        │ ╭─ postgresql/0* ─╮                      │ ╭─ pgbouncer/1 ───────────────────────────────╮ │
│                  │ │ <empty>         │                      │ │                                             │ │
│                  │ ╰─────────────────╯                      │ │  data  {"endpoints": "10.180.162.236:5432", │ │
│                  │                                          │ │         "password": "yPEgUWCYX0SBxpvC",     │ │
│                  │                                          │ │         "username": "relation-3",           │ │
│                  │                                          │ │         "version": "12.12"}                 │ │
│                  │                                          │ ╰─────────────────────────────────────────────╯ │
│                  │                                          │ ╭─ pgbouncer/2* ──────────────────────────────╮ │
│                  │                                          │ │                                             │ │
│                  │                                          │ │  data  {"endpoints": "10.180.162.236:5432", │ │
│                  │                                          │ │         "password": "yPEgUWCYX0SBxpvC",     │ │
│                  │                                          │ │        "username": "relation-3",            │ │
│                  │                                          │ │         "version": "12.12"}                 │ │
│                  │                                          │ ╰─────────────────────────────────────────────╯ │
-----------------------------------------------------------------------------------------------------------------

"""  # noqa: W505

import logging
from typing import Dict, List, Set

import psycopg2
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseCreatedEvent,
    DatabaseRequires,
)
from charms.pgbouncer_k8s.v0 import pgb
from charms.postgresql_k8s.v0.postgresql import PostgreSQL
from ops.charm import CharmBase, RelationBrokenEvent, RelationDepartedEvent
from ops.framework import Object
from ops.model import (
    ActiveStatus,
    Application,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
)

from constants import (
    APP_SCOPE,
    AUTH_FILE_NAME,
    BACKEND_RELATION_NAME,
    MONITORING_PASSWORD_KEY,
    PG,
    PGB,
    PGB_CONF_DIR,
)

logger = logging.getLogger(__name__)


class BackendDatabaseRequires(Object):
    """Defines functionality for the 'requires' side of the 'backend-database' relation.

    The data created in this relation allows the pgbouncer charm to connect to the postgres charm.

    Hook events observed:
        - database-created
        - database-endpoints-changed
        - database-read-only-endpoints-changed
        - relation-departed
        - relation-broken
    """

    def __init__(self, charm: CharmBase):
        super().__init__(charm, BACKEND_RELATION_NAME)

        self.charm = charm
        self.database = DatabaseRequires(
            self.charm,
            relation_name=BACKEND_RELATION_NAME,
            database_name=PGB,
            extra_user_roles="SUPERUSER",
        )

        self.framework.observe(self.database.on.database_created, self._on_database_created)
        self.framework.observe(
            charm.on[BACKEND_RELATION_NAME].relation_changed, self._on_relation_changed
        )
        self.framework.observe(self.database.on.endpoints_changed, self._on_endpoints_changed)
        self.framework.observe(
            self.database.on.read_only_endpoints_changed, self._on_endpoints_changed
        )
        self.framework.observe(
            charm.on[BACKEND_RELATION_NAME].relation_departed, self._on_relation_departed
        )
        self.framework.observe(
            charm.on[BACKEND_RELATION_NAME].relation_broken, self._on_relation_broken
        )

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Handle backend-database-database-created event.

        Accesses user and password generated by the postgres charm and adds a user.
        """
        logger.info("initialising postgres and pgbouncer relations")
        self.charm.unit.status = MaintenanceStatus("Initialising backend-database relation")
        if not self.charm.unit.is_leader():
            return
        if self.postgres is None:
            event.defer()
            logger.error("deferring database-created hook - postgres database not ready")
            return

        plaintext_password = pgb.generate_password()
        hashed_password = pgb.get_hashed_password(self.auth_user, plaintext_password)
        # create authentication user on postgres database, so we can authenticate other users
        # later on
        self.postgres.create_user(self.auth_user, hashed_password, admin=True)
        self.initialise_auth_function([self.database.database, PG])

        # Add the monitoring user.
        if not (monitoring_password := self.charm.get_secret(APP_SCOPE, MONITORING_PASSWORD_KEY)):
            monitoring_password = pgb.generate_password()
            self.charm.set_secret("app", MONITORING_PASSWORD_KEY, monitoring_password)
        hashed_monitoring_password = pgb.get_hashed_password(self.stats_user, monitoring_password)

        self.charm.render_auth_file(
            f'"{self.auth_user}" "{hashed_password}"\n"{self.stats_user}" "{hashed_monitoring_password}"'
        )

        cfg = self.charm.read_pgb_config()
        cfg.add_user(user=self.stats_user, stats=True)
        cfg["pgbouncer"]["auth_query"] = (
            f"SELECT username, password FROM {self.auth_user}.get_auth($1)"
        )
        cfg["pgbouncer"]["auth_file"] = f"{PGB_CONF_DIR}/{self.charm.app.name}/{AUTH_FILE_NAME}"
        self.charm.render_pgb_config(cfg)
        self.charm.render_prometheus_service()

        self.charm.update_postgres_endpoints(reload_pgbouncer=True)

        self.charm.unit.status = ActiveStatus("backend-database relation initialised.")

    def _on_endpoints_changed(self, _):
        self.charm.update_postgres_endpoints(reload_pgbouncer=True)
        if self.charm.unit.is_leader():
            self.charm.update_client_connection_info()

    def _on_relation_changed(self, _):
        self.charm.update_postgres_endpoints(reload_pgbouncer=True)
        if self.charm.unit.is_leader():
            self.charm.update_client_connection_info()

    def _on_relation_departed(self, event: RelationDepartedEvent):
        """Runs pgbouncer-uninstall.sql and removes auth user.

        This hook has to run user removal hooks before relation-broken events are fired, because
        the postgres relation-broken hook removes the user needed to remove authentication for the
        users we create.
        """
        if self.charm.unit.is_leader():
            self.charm.update_client_connection_info()
        self.charm.update_postgres_endpoints(reload_pgbouncer=True)

        if event.departing_unit == self.charm.unit:
            self.charm.peers.unit_databag.update({
                f"{BACKEND_RELATION_NAME}_{event.relation.id}_departing": "true"
            })
            logger.error("added relation-departing flag to peer databag")
            return

        if not self.charm.unit.is_leader() or event.departing_unit.app != self.charm.app:
            # this doesn't trigger if we're scaling the other app.
            return

        planned_units = self.charm.app.planned_units()
        if planned_units < len(self.charm.peers.relation.units) and planned_units != 0:
            # check that we're scaling down, but remove the relation if we're removing pgbouncer
            # entirely.
            return

        try:
            # TODO de-authorise all databases
            logger.info("removing auth user")
            self.remove_auth_function([PGB, PG])
        except psycopg2.Error:
            remove_auth_fail_msg = (
                "failed to remove auth user when disconnecting from postgres application."
            )
            self.charm.unit.status = BlockedStatus(remove_auth_fail_msg)
            logger.error(remove_auth_fail_msg)
            return

        self.postgres.delete_user(self.auth_user)
        logger.info("pgbouncer auth user removed")

    def _on_relation_broken(self, event: RelationBrokenEvent):
        """Handle backend-database-relation-broken event.

        Removes all traces of this relation from pgbouncer config.
        """
        depart_flag = f"{BACKEND_RELATION_NAME}_{event.relation.id}_departing"
        if (
            self.charm.peers.unit_databag.get(depart_flag, False)
            or not self.charm.unit.is_leader()
        ):
            logging.info("exiting relation-broken hook - nothing to do")
            return

        try:
            cfg = self.charm.read_pgb_config()
        except FileNotFoundError:
            event.defer()
            return

        if self.postgres:
            cfg.remove_user(self.postgres.user)
        cfg["pgbouncer"].pop("stats_users", None)
        cfg["pgbouncer"].pop("auth_query", None)
        cfg["pgbouncer"].pop("auth_file", None)
        self.charm.render_pgb_config(cfg)

        self.charm.delete_file(f"{PGB_CONF_DIR}/userlist.txt")
        self.charm.peers.update_auth_file(auth_file=None)

        self.charm.remove_exporter_service()

    def initialise_auth_function(self, dbs: List[str]):
        """Runs an SQL script to initialise the auth function.

        This function must run in every database for authentication to work correctly, and assumes
        self.postgres is set up correctly.

        Args:
            dbs: a list of database names to connect to.

        Raises:
            psycopg2.Error if self.postgres isn't usable.
        """
        logger.info("initialising auth function")
        install_script = open("src/relations/sql/pgbouncer-install.sql", "r").read()

        for dbname in dbs:
            with self.postgres._connect_to_database(dbname) as conn, conn.cursor() as cursor:
                cursor.execute(install_script.replace("auth_user", self.auth_user))
            conn.close()
        logger.info("auth function initialised")

    def remove_auth_function(self, dbs: List[str]):
        """Runs an SQL script to remove auth function.

        pgbouncer-uninstall doesn't actually uninstall anything - it actually removes permissions
        for the auth user.

        Args:
            dbs: a list of database names to connect to.

        Raises:
            psycopg2.Error if self.postgres isn't usable.
        """
        logger.info("removing auth function from backend relation")
        uninstall_script = open("src/relations/sql/pgbouncer-uninstall.sql", "r").read()
        for dbname in dbs:
            with self.postgres._connect_to_database(dbname) as conn, conn.cursor() as cursor:
                cursor.execute(uninstall_script.replace("auth_user", self.auth_user))
            conn.close()
        logger.info("auth function removed")

    @property
    def relation(self) -> Relation:
        """Relation object for postgres backend-database relation."""
        backend_relation = self.model.get_relation(BACKEND_RELATION_NAME)
        if not backend_relation:
            return None
        else:
            return backend_relation

    @property
    def postgres(self) -> PostgreSQL:
        """Returns PostgreSQL representation of backend database, as defined in relation.

        Returns None if backend relation is not fully initialised.
        """
        if not self.relation:
            return None

        databag = self.postgres_databag
        endpoint = databag.get("endpoints")
        user = self.database.fetch_relation_field(self.relation.id, "username")
        password = self.database.fetch_relation_field(self.relation.id, "password")
        database = self.database.database

        if None in [endpoint, user, password]:
            return None

        return PostgreSQL(
            primary_host=endpoint.split(":")[0],
            current_host=endpoint.split(":")[0],
            user=user,
            password=password,
            database=database,
        )

    @property
    def auth_user(self):
        """Username for auth_user."""
        if not self.relation:
            return None

        username = self.database.fetch_relation_field(self.relation.id, "username")
        if username is None:
            return None
        return f"pgbouncer_auth_{username}".replace("-", "_")

    @property
    def stats_user(self):
        """Username for stats."""
        return f"pgbouncer_stats_{self.charm.app.name}".replace("-", "_")

    @property
    def postgres_databag(self) -> Dict:
        """Wrapper around accessing the remote application databag for the backend relation.

        Returns None if relation is none.

        Since we can trigger db-relation-changed on backend-changed, we need to be able to easily
        access the backend app relation databag.
        """
        if self.relation:
            for key, databag in self.relation.data.items():
                if isinstance(key, Application) and key != self.charm.app:
                    return databag
        return None

    @property
    def ready(self) -> bool:
        """A boolean signifying whether the backend relation is fully initialised & ready."""
        # Check we have connection information
        if not self.postgres:
            return False

        # Check we can authenticate
        cfg = self.charm.read_pgb_config()
        if "auth_query" not in cfg["pgbouncer"].keys():
            return False

        # Check we can actually connect to backend database by running a command.
        try:
            with self.postgres._connect_to_database(PGB) as conn, conn.cursor() as cursor:
                # TODO find a better smoke check
                cursor.execute("SELECT version();")
            conn.close()
        except (psycopg2.Error, psycopg2.OperationalError):
            logger.error("PostgreSQL connection failed")
            return False

        return True

    def get_read_only_endpoints(self) -> Set[str]:
        """Get read-only-endpoints from backend relation."""
        read_only_endpoints = self.postgres_databag.get("read-only-endpoints", None)
        if not read_only_endpoints:
            return set()
        return set(read_only_endpoints.split(","))
