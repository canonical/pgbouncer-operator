# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres db relation hooks & helpers.

This relation uses the pgsql interface.

Some example relation data is below. All values are examples, generated in a running test instance.
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ category  ┃          keys ┃ pgbouncer/25                                      ┃ psql/1 ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ metadata  │      endpoint │ 'db'                                              │ 'db'   │
│           │        leader │ True                                              │ True   │
├───────────┼───────────────┼───────────────────────────────────────────────────┼────────┤
│ unit data │ allowed-units │ psql/1                                            │        │
│           │      database │ cli                                               │ cli    │
│           │          host │ 10.101.233.10                                     │        │
│           │        master │ dbname=cli host=10.101.233.10                     │        │
│           │               │ password=jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs │        │
│           │               │ port=6432 user=db_85_psql                         │        │
│           │      password │ jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs          │        │
│           │          port │ 6432                                              │        │
│           │      standbys │ dbname=cli_standby host=10.101.233.10             │        │
│           │               │ password=jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs │        │
│           │               │ port=6432 user=db_85_psql                         │        │
│           │         state │ master                                            │        │
│           │          user │ db_85_psql                                        │        │
│           │       version │ 12                                                │        │
└───────────┴───────────────┴───────────────────────────────────────────────────┴────────┘
"""

import logging
from typing import Iterable, List

import psycopg2
from charms.pgbouncer_operator.v0 import pgb
from charms.pgbouncer_operator.v0.pgb import PgbConfig
from ops.charm import (
    CharmBase,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
)
from ops.framework import Object
from ops.model import Relation, Unit
from psycopg2.sql import Identifier

from constants import BACKEND_STANDBY_PREFIX

logger = logging.getLogger(__name__)

STANDBY_PREFIX_LEN = len(BACKEND_STANDBY_PREFIX)


class DbProvides(Object):
    """Defines functionality for the 'requires' side of the 'db' relation.

    Hook events observed:
        - relation-changed
        - relation-departed
        - relation-broken
    """

    def __init__(self, charm: CharmBase, admin: bool = False):
        """Constructor for DbProvides object.

        Args:
            charm: the charm for which this relation is provided
            admin: a boolean defining whether or not this relation has admin permissions, switching
                between "db" and "db-admin" relations.
        """
        if admin:
            self.relation_name = "db-admin"
        else:
            self.relation_name = "db"

        super().__init__(charm, self.relation_name)

        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed, self._on_relation_departed
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_broken, self._on_relation_broken
        )

        self.charm = charm
        self.admin = admin

    def _on_relation_changed(self, change_event: RelationChangedEvent):
        """Handle db-relation-changed event.

        Takes information from the db relation databag and copies it into the pgbouncer.ini
        config.
        """
        if not self.charm.unit.is_leader():
            return

        logger.info(f"Setting up {change_event.relation.name} relation - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]
        if not dbs.get("pg_master"):
            # wait for backend_db_admin relation to populate config before we use it.
            logger.warning("waiting for backend-db-admin relation")
            change_event.defer()
            return

        relation_data = change_event.relation.data
        pgb_unit_databag = relation_data[self.charm.unit]
        pgb_app_databag = relation_data[self.charm.app]
        try:
            external_unit = self.get_external_units(change_event.relation)[0]
        except IndexError:
            # In cases where pgbouncer changes the relation, we have no new information to add to
            # the config. Scaling is not yet implemented, and calling this hook from the
            # backend-db-admin relation occurs after the config updates are added.
            logger.info(
                f"no external unit found in {self.relation_name} relation - nothing to change in config, exiting relation hook"
            )
            return
        external_app_name = external_unit.app.name

        database = pgb_app_databag.get("database", relation_data[external_unit].get("database"))
        if database is None:
            logger.warning("No database name provided")
            change_event.defer()
            return
        database = database.replace("-", "_")
        user = pgb_app_databag.get("user", self.generate_username(change_event, external_app_name))
        password = pgb_app_databag.get("password", pgb.generate_password())

        # Get data about primary unit for databags and charm config.
        master_host = dbs["pg_master"]["host"]
        master_port = dbs["pg_master"]["port"]
        primary = {
            "host": master_host,
            "dbname": database,
            "port": master_port,
            "user": user,
            "password": password,
            "fallback_application_name": external_app_name,
        }
        dbs[database] = primary

        # Get data about standby units for databags and charm config.
        standbys = self._get_postgres_standbys(cfg, external_app_name, database, user, password)

        # Get postgres roles and extensions if they exist
        roles = set(
            role.strip() for role in relation_data[external_unit].get("roles", "").split(",")
        )
        extensions = set(
            ext.strip() for ext in relation_data[external_unit].get("extensions", "").split(",")
        )

        # Generate users and databases
        if not self._generate_remote_data(cfg, user, password, database, extensions, roles):
            logger.error(f"unable to generate backend data for {self.relation_name} relation.")
            change_event.defer()
            return

        # Populate databags
        for databag in [pgb_app_databag, pgb_unit_databag]:
            databag["allowed-subnets"] = self.get_allowed_subnets(change_event.relation)
            databag["allowed-units"] = self.get_allowed_units(change_event.relation)
            databag["host"] = f"http://{master_host}"
            databag["master"] = pgb.parse_dict_to_kv_string(primary)
            databag["port"] = master_port
            databag["standbys"] = standbys
            databag["version"] = "12"
            databag["user"] = user
            databag["password"] = password
            databag["database"] = database
            if roles:
                databag["roles"] = ",".join(roles)
            if extensions:
                databag["extensions"] = ",".join(extensions)
        pgb_unit_databag["state"] = self._get_state(standbys)

        # Write config data to charm filesystem
        self.charm.add_user(user, password, admin=self.admin, cfg=cfg, render_cfg=False)
        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def generate_username(self, event, app_name):
        """Generates a username for this relation."""
        return f"{self.relation_name}_{event.relation.id}_{app_name.replace('-', '_')}"

    def _get_postgres_standbys(self, cfg, app_name, database, user, password):
        dbs = cfg["databases"]

        standbys = ""
        for standby_name, standby_data in dict(dbs).items():
            # skip everything that's not a postgres standby, as defined by the backend-db-admin
            # relation
            if standby_name[:STANDBY_PREFIX_LEN] != BACKEND_STANDBY_PREFIX:
                continue

            standby_idx = standby_name[STANDBY_PREFIX_LEN:]
            standby = {
                "host": standby_data["host"],
                "dbname": database,
                "port": standby_data["port"],
                "user": user,
                "password": password,
                "fallback_application_name": app_name,
            }
            dbs[f"{database}_standby_{standby_idx}"] = standby

            standbys += pgb.parse_dict_to_kv_string(standby) + ","

        # Strip final comma off standby string
        standbys = standbys[:-1]
        return standbys

    def _get_state(self, standbys: str) -> str:
        """Gets the given state for this unit.

        Args:
            standbys: the comma-separated list of postgres standbys

        Returns:
            The described state of this unit. Can be 'standalone', 'master', or 'standby'.
        """
        if standbys == "":
            return "standalone"
        if self.charm.unit.is_leader():
            return "master"
        else:
            return "standby"

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """Handle db-relation-departed event.

        Removes relevant information from pgbouncer config when db relation is removed. This
        function assumes that relation databags are destroyed when the relation itself is removed.

        This doesn't delete users or tables, following the design of the legacy charm.
        """
        logger.info("db relation removed - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        app_databag = departed_event.relation.data[self.charm.app]
        unit_databag = departed_event.relation.data[self.charm.unit]

        for databag in [app_databag, unit_databag]:
            databag["allowed-units"] = self.get_allowed_units(departed_event.relation)

    def _on_relation_broken(self, broken_event: RelationBrokenEvent):
        """Handle db-relation-broken event.

        Removes all traces of the given application from the pgbouncer config.
        """
        app_databag = broken_event.relation.data[self.charm.app]

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]
        user = app_databag["user"]
        database = app_databag["database"]

        del dbs[database]
        for db in list(dbs.keys()):
            if f"{database}_standby_" in dbs[db]["dbname"]:
                del dbs[db]

        self.charm.remove_user(user, cfg=cfg, render_cfg=False)
        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def get_allowed_subnets(self, relation: Relation) -> str:
        """Gets the allowed subnets from this relation."""

        def _comma_split(string) -> Iterable[str]:
            if string:
                for substring in string.split(","):
                    substring = substring.strip()
                    if substring:
                        yield substring

        subnets = set()
        for unit, reldata in relation.data.items():
            logger.warning(f"Checking subnets for {unit}")
            if isinstance(unit, Unit) and not unit.name.startswith(self.model.app.name):
                # NB. egress-subnets is not always available.
                subnets.update(set(_comma_split(reldata.get("egress-subnets", ""))))
        return ",".join(sorted(subnets))

    def get_allowed_units(self, relation: Relation) -> str:
        """Gets the external units from this relation that can be allowed into the network."""
        return ",".join(sorted([unit.name for unit in self.get_external_units(relation)]))

    def get_external_units(self, relation: Relation) -> Unit:
        """Gets all units from this relation that aren't owned by this charm."""
        return [
            unit
            for unit in relation.data
            if isinstance(unit, Unit) and not unit.name.startswith(self.model.app.name)
        ]

    # ====================
    #  Postgres Utilities
    # ====================

    def _generate_remote_data(self, cfg, user, password, database, extensions, roles):
        try:
            con = self.get_backend_connection(cfg)
            self.ensure_user(con, user, password, roles, self.admin)
            self.ensure_database(con, user, database)
            self.ensure_extensions(database, extensions)
        except psycopg2.OperationalError:
            logger.warning("unable to initialise databases/users/extensions")
            return False
        finally:
            if con is None:
                return False
            else:
                con.close()
        return True

    def get_backend_connection(self, cfg: PgbConfig) -> psycopg2.extensions.connection:
        """Gets a psycopg2.Connection object to the backend database.

        Returns:
            psycopg2.Connection object, linked to backend database
        """
        if not self.charm._has_backend_relation():
            logger.info(
                "unable to connect to backend database - backend-db-admin relation not connected"
            )
            return None

        backend = cfg["databases"].get("pg_master")
        if backend is None:
            return None

        logger.error(pgb.parse_dict_to_kv_string(backend))
        connection = psycopg2.connect(pgb.parse_dict_to_kv_string(backend))
        connection.autocommit = True
        return connection

    def ensure_user(
        self, connection, user: str, password: str, roles: List[str], admin: bool = False
    ) -> None:
        """Ensure the given extensions exist for the database to which we are connected.

        Args:
            connection: psycopg2.extensions.connection object, connected to the expected database.
            user: the user to be created.
            roles: a list of strings, representing the roles the user has.
            admin: a boolean signifying whether this user has admin permissions.

        Raises:
            psycopg2.OperationalError
        """
        cur = connection.cursor()
        if not self._role_exists(connection, user):
            if admin:
                logger.info("Creating superuser {}".format(user))
                cur.execute(
                    "CREATE ROLE %s WITH SUPERUSER LOGIN PASSWORD %s",
                    (Identifier(user).string, password),
                )
            else:
                logger.info("Creating user {}".format(user))
                cur.execute(
                    "CREATE ROLE %s WITH LOGIN PASSWORD %s", (Identifier(user).string, password)
                )

        # Reset the user's roles.
        wanted_roles = set(roles)
        cur.execute(
            """
            SELECT role.rolname
            FROM pg_roles AS role, pg_roles AS member, pg_auth_members
            WHERE
                member.oid = pg_auth_members.member
                AND role.oid = pg_auth_members.roleid
                AND member.rolname = %s
            """,
            (user,),
        )
        existing_roles = set(r[0] for r in cur.fetchall())
        roles_to_grant = wanted_roles.difference(existing_roles)
        roles_to_revoke = existing_roles.difference(wanted_roles)

        for role in roles_to_grant:
            if not self._role_exists(connection, role):
                logger.info("Creating role {}".format(role))
                cur.execute("CREATE ROLE %s INHERIT NOLOGIN", (Identifier(role).string,))
            logger.info("Granting {} to {}".format(role, user))
            cur.execute("GRANT %s TO %s", (Identifier(role).string, Identifier(user)))

        for role in roles_to_revoke:
            logger.info("Revoking {} from {}".format(role, user))
            cur.execute("REVOKE %s FROM %s", (Identifier(role).string, Identifier(user)))

    def _role_exists(self, con, role):
        cur = con.cursor()
        cur.execute("SELECT rolname FROM pg_roles WHERE rolname = %s", (role,))
        return cur.fetchone() is not None

    def ensure_database(self, connection, user: str, database: str) -> None:
        """Ensure the given extensions exist for the database to which we are connected.

        Args:
            connection: psycopg2.extensions.connection object, connected to the expected database.
            user: the intended owner of the database.
            database: the database whose existence should be ensured.

        Raises:
            psycopg2.OperationalError
        """
        cur = connection.cursor()
        try:
            cur.execute("SELECT datname FROM pg_database WHERE datname = %s", (database,))
            if not cur.fetchone():
                logger.info("Creating database {}".format(database))
                cur.execute("CREATE DATABASE %s", (Identifier(database).string,))
            cur.execute(
                "GRANT CONNECT ON DATABASE %s TO %s",
                (Identifier(database).string, Identifier(user).string),
            )
        except psycopg2.IntegrityError:
            # Race with another unit. DB already created.
            pass

    def ensure_extensions(self, connection, extensions: List[str]) -> None:
        """Ensure the given extensions exist for the database to which we are connected.

        Args:
            connection: psycopg2.extensions.connection object, connected to the expected database.
            extensions: a list of extensions to be created, each represented as a string.

        Raises:
            psycopg2.OperationalError
        """
        with connection.cursor() as cur:
            for ext in extensions:
                cur.execute("CREATE EXTENSION IF NOT EXISTS %s", (Identifier(ext).string,))
