# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres db relation hooks & helpers.

This relation uses the pgsql interface.

Some example relation data is below. All values are examples, generated in a running test instance.
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ category  ┃          keys ┃ pgbouncer/25                                                                   ┃ psql/1 ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ metadata  │      endpoint │ 'db'                                                                           │ 'db'   │
│           │        leader │ True                                                                           │ True   │
├───────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────┼────────┤
│ unit data │ allowed-units │ psql/1                                                                         │        │
│           │      database │ cli                                                                            │ cli    │
│           │          host │ 10.101.233.10                                                                  │        │
│           │        master │ dbname=cli host=10.101.233.10                                                  │        │
│           │               │ password=jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs port=6432 user=db_85_psql    │        │
│           │      password │ jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs                                       │        │
│           │          port │ 6432                                                                           │        │
│           │      standbys │ dbname=cli_standby host=10.101.233.10                                          │        │
│           │               │ password=jnT4LxNPPrssscxGYmGPy4FKjRNXCn4NL2Y32jqs port=6432 user=db_85_psql    │        │
│           │         state │ master                                                                         │        │
│           │          user │ db_85_psql                                                                     │        │
│           │       version │ 12                                                                             │        │
└───────────┴───────────────┴────────────────────────────────────────────────────────────────────────────────┴────────┘
"""

import logging

from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase, RelationChangedEvent, RelationDepartedEvent
from ops.framework import Object

logger = logging.getLogger(__name__)

RELATION_ID = "db"


class DbProvides(Object):
    """Defines functionality for the 'requires' side of the 'db' relation.

    Hook events observed:
        - relation-changed
        - relation-departed
    """

    def __init__(self, charm: CharmBase):
        super().__init__(charm, RELATION_ID)

        self.framework.observe(charm.on[RELATION_ID].relation_changed, self._on_relation_changed)
        self.framework.observe(charm.on[RELATION_ID].relation_departed, self._on_relation_departed)

        self.charm = charm

    def _on_relation_changed(self, change_event: RelationChangedEvent):
        """Handle db-relation-changed event.

            Takes information from the db-admin relation
        def __init__(self, charm: CharmBase):databag and copies it into the pgbouncer.ini
            config.
        """
        if not self.charm.is_leader():
            return

        logger.info(f"Setting up {change_event.relation.name} relation - updating config")
        logger.info(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        unit_relation_databag = change_event.relation.data[self.unit]
        application_relation_databag = change_event.relation.data[self.app]

        # Check whether relation already exists
        relation_exists = False
        if application_relation_databag.get("user"):
            relation_exists = True

        database = (
            unit_relation_databag["database"]
            if relation_exists
            else change_event.relation.data[change_event.app].get("database")
        )
        if not database:
            logger.warning("No database name provided")
            change_event.defer()
            return

        # TODO maybe del
        hostname = self._get_hostname_from_unit(self.unit.name.replace("/", "-"))
        connection = connect_to_database(
            "postgres", "postgres", hostname, self._get_postgres_password()
        )
        logger.info(f"Connected to PostgreSQL: {connection}")

        user = (
            unit_relation_databag["user"]
            if relation_exists
            else f"relation_id_{change_event.relation.id}_{change_event.app.name.replace('-', '_')}"
        )
        password = unit_relation_databag["password"] if relation_exists else self._new_password()

        database = database.replace("-", "_")

        if not relation_exists:
            create_user(connection, user, password, admin=relation_name == RELATION_ID)
            create_database(connection, database, user)

        connection.close()

        members = self._patroni.cluster_members
        primary = str(
            ConnectionString(
                host=f"{self._get_hostname_from_unit(self._patroni.get_primary())}",
                dbname=database,
                port=5432,
                user=user,
                password=password,
                fallback_application_name=change_event.app.name,
            )
        )
        standbys = ",".join(
            [
                str(
                    ConnectionString(
                        host=f"{self._get_hostname_from_unit(member)}",
                        dbname=database,
                        port=5432,
                        user=user,
                        password=password,
                        fallback_application_name=change_event.app.name,
                    )
                )
                for member in members
                if self._get_hostname_from_unit(member) != primary
            ]
        )

        for databag in [application_relation_databag, unit_relation_databag]:
            databag["allowed-subnets"] = self.get_allowed_subnets(change_event.relation)
            databag["allowed-units"] = self.get_allowed_units(change_event.relation)
            databag["host"] = f"http://{hostname}"
            databag["master"] = primary
            databag["port"] = "5432"
            databag["standbys"] = standbys
            databag["state"] = "master"
            databag["version"] = "12"
            databag["user"] = user
            databag["password"] = password
            databag["database"] = database

        self.charm.unit.status = ActiveStatus()

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """Handle db-relation-departed event.

        Removes relevant information from pgbouncer config when db-admin relation is removed.
        """
        if not self.charm.is_leader():
            return

        logger.info("db relation removed - updating config")
        logger.info(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        cfg = self.charm._read_pgb_config()

        # TODO remove relevant info from cfg. Should this delete database tables? Does this happen
        #      automatically?

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)
