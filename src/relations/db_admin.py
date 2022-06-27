# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres db-admin relation hooks & helpers.

The db-admin relation effectively does the same thing as db, but the user that it adds is given
administrative permissions. This relation uses the pgsql interface.

Some example relation data is below. All values are examples, generated in a running test instance.
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ category  ┃          keys ┃ pgbouncer/23                                              ┃ psql/0 ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ metadata  │      endpoint │ 'db-admin'                                                │ 'db'   │
│           │        leader │ True                                                      │ True   │
├───────────┼───────────────┼───────────────────────────────────────────────────────────┼────────┤
│ unit data │ allowed-units │ psql/0                                                    │        │
│           │      database │ cli                                                       │ cli    │
│           │          host │ 10.101.233.178                                            │        │
│           │        master │ dbname=cli host=10.101.233.178                            │        │
│           │               │ password=JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K           │        │
│           │               │ port=6432 user=db_admin_80_psql                           │        │
│           │      password │ JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K                    │        │
│           │          port │ 6432                                                      │        │
│           │      standbys │ dbname=cli_standby host=10.101.233.178                    │        │
│           │               │ password=JWjVc9PbXHSTL3RrXt9tT6xf43zbJBc4HPdb7K port=6432 │        │
│           │               │ user=db_admin_80_psql                                     │        │
│           │         state │ master                                                    │        │
│           │          user │ db_admin_80_psql                                          │        │
│           │       version │ 12                                                        │        │
└───────────┴───────────────┴───────────────────────────────────────────────────────────┴────────┘
"""

import logging
from typing import Iterable

from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase, RelationChangedEvent, RelationDepartedEvent
from ops.framework import Object
from ops.model import Relation, Unit
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
        """Handle db-adminrelation-changed event.

        Takes information from the db-admin relation databag and copies it into the pgbouncer.ini
        config.
        """
        if not self.charm.is_leader:
            return

        logger.info(f"Setting up {change_event.relation.name} relation - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        unit_databag = change_event.relation.data[self.charm.unit]
        app_databag = change_event.relation.data[self.charm.app]

        # Check if the application databag is already populated, and store var as an explicit
        app_databag_populated = app_databag.get("user") is not None

        if app_databag_populated:
            database = unit_databag["database"]
            user = unit_databag["user"]
            password = unit_databag["password"]
        else:
            database = change_event.relation.data[change_event.unit].get("database")
            user = f"{change_event.relation.id}_{change_event.unit.name.replace('-', '_')}"
            password = pgb.generate_password()

        if not database:
            logger.warning("No database name provided")
            change_event.defer()
            return

        database = database.replace("-", "_")

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]

        self.charm.add_user(user, password, admin=True, cfg=cfg, render_cfg=False)

        if not dbs.get("pg_master"):
            # wait for backend_db_admin relation to populate config.
            logger.warning("waiting for backend-db-admin relation")
            change_event.defer()
            return

        master_host = dbs["pg_master"]["host"]
        master_port = dbs["pg_master"]["port"]

        primary = {
            "host": master_host,
            "dbname": database,
            "port": master_port,
            "user": user,
            "password": password,
            "fallback_application_name": change_event.app.name,
        }

        dbs[database] = primary

        standbys = []
        for standby_name, standby_data in dbs.items():
            # skip everything that's not a postgres standby.
            if standby_name[:21] != "pgb_postgres_standby_":
                continue

            standby_idx = int(standby_name[21:])
            standby = {
                "host": standby_data["host"],
                "dbname": database,
                "port": standby_data["port"],
                "user": user,
                "password": password,
                "fallback_application_name": change_event.app.name,
            }

            standbys.append(standby)

        standby_str = ""
        for standby in standbys:
            dbs[f"{database}_standby_{standby_idx}"] = standby
            standby_str += pgb.parse_dict_to_kv_string(standby) + ","

        standby_str = standby_str[:-1]

        for databag in [app_databag, unit_databag]:
            databag["allowed-subnets"] = self.get_allowed_subnets(change_event.relation)
            databag["allowed-units"] = self.get_allowed_units(change_event.relation)
            databag["host"] = f"http://{master_host}"
            databag["master"] = pgb.parse_dict_to_kv_string(primary)
            databag["port"] = master_port
            databag["standbys"] = standby_str
            databag["state"] = "master"
            databag["version"] = "12"
            databag["user"] = user
            databag["password"] = password
            databag["database"] = database

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """Handle db-admin-relation-departed event.

        Removes relevant information from pgbouncer config when db-admin relation is removed. This
        function assumes that relation databags are destroyed when the relation itself is removed.

        This doesn't delete users or tables, following the design of the legacy charm.

        TODO remove correct units when unit is removed

        """
        if not self.charm.is_leader:
            return

        logger.info("db relation removed - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        app_databag = departed_event.relation.data[self.charm.app]

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]

        user = app_databag["user"]
        database = app_databag["database"]
        self.charm.remove_user(user, cfg=cfg, render_cfg=False)

        del dbs[database]
        # Delete replicas
        # TODO find a smarter way of doing this
        for db in list(dbs.keys()):
            if dbs[db]["name"].contains(f"{database}_standby_"):
                del dbs[db]

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def get_allowed_subnets(self, relation: Relation) -> str:
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
        return ",".join(
            sorted(
                unit.name
                for unit in relation.data
                if isinstance(unit, Unit) and not unit.name.startswith(self.model.app.name)
            )
        )
