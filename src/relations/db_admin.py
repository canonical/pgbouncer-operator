# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres db-admin relation hooks & helpers.

The db-admin relation effectively does the same thing as db, but the user that it adds is given
administrative permissions. This relation uses the pgsql interface.

Some example relation data is below. All values are examples, generated in a running test instance.
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ category  ┃          keys ┃ pgbouncer/23                                                                   ┃ psql/0 ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ metadata  │      endpoint │ 'db-admin'                                                                     │ 'db'   │
│           │        leader │ True                                                                           │ True   │
├───────────┼───────────────┼────────────────────────────────────────────────────────────────────────────────┼────────┤
│ unit data │ allowed-units │ psql/0                                                                         │        │
│           │      database │ cli                                                                            │ cli    │
│           │          host │ 10.101.233.178                                                                 │        │
│           │        master │ dbname=cli host=10.101.233.178 password=JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K │        │
│           │               │ port=6432 user=db_admin_80_psql                                                │        │
│           │      password │ JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K                                         │        │
│           │          port │ 6432                                                                           │        │
│           │      standbys │ dbname=cli_standby host=10.101.233.178                                         │        │
│           │               │ password=JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K port=6432                      │        │
│           │               │ user=db_admin_80_psql                                                          │        │
│           │         state │ master                                                                         │        │
│           │          user │ db_admin_80_psql                                                               │        │
│           │       version │ 12                                                                             │        │
└───────────┴───────────────┴────────────────────────────────────────────────────────────────────────────────┴────────┘
"""

import logging

from charms.postgresql.v0.postgresql_helpers import (
    connect_to_database,
    create_database,
    create_user,
)
from ops.charm import CharmBase, RelationChangedEvent, RelationDepartedEvent
from ops.framework import Object
from pgconnstr import ConnectionString

logger = logging.getLogger(__name__)

RELATION_ID = "db-admin"


class DbAdminProvides(Object):
    """Defines functionality for the 'requires' side of the 'db-admin' relation.

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
        """Handle db-admin-relation-changed event.

        Takes information from the db-admin relation databag and copies it into the pgbouncer.ini
        config.
        """
        if not self.charm.is_leader():
            return

        logger.info(f"Setting up {change_event.relation.name} relation - updating config")
        logger.warning(
            "DEPRECATION WARNING - db-admin is a legacy relation, and will be deprecated in a future release. "
        )

        event_data = change_event.relation.data
        logger.info(event_data)

        unit_relation_databag = change_event.relation.data[self.unit]
        application_relation_databag = change_event.relation.data[self.app]
        logger.info(unit_relation_databag)
        logger.info(application_relation_databag)

        # Check if the application databag is already populated.
        already = False
        if application_relation_databag.get("user"):
            already = True

        hostname = self._get_hostname_from_unit(self.charm.unit.name.replace("/", "-"))
        connection = connect_to_database(
            "postgres", "postgres", hostname, self._get_postgres_password()
        )

        user = (
            unit_relation_databag["user"]
            if already
            else f"{change_event.relation.id}_{change_event.app.name.replace('-', '_')}"
        )
        cfg["pgbouncer"]["admin_users"].append(user)

        password = unit_relation_databag["password"] if already else self._new_password()
        database = (
            unit_relation_databag["database"]
            if already
            else change_event.relation.data[change_event.app].get("database")
        )
        if not database:
            logger.warning("No database name provided")
            change_event.defer()
            return

        database = database.replace("-", "_")

        if not already:
            create_user(connection, user, password, admin=True)
            create_database(connection, database, user)

        connection.close()

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

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """Handle db-admin-relation-departed event.

        Removes relevant information from pgbouncer config when db-admin relation is removed.
        """
        if not self.charm.is_leader():
            return

        logger.info("db-admin relation removed - updating config")
        logger.info(
            "DEPRECATION WARNING - db-admin is a legacy relation, and will be deprecated in a future release. "
        )

        cfg = self.charm._read_pgb_config()

        # TODO remove relevant info from cfg. Should this delete database tables? Does this happen
        #      automatically?

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)
