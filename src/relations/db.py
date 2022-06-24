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
from pgconnstr import ConnectionString

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

        Takes information from the db relation databag and copies it into the pgbouncer.ini
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
            database = change_event.relation.data[change_event.app].get("database")
            user = f"{change_event.relation.id}_{change_event.app.name.replace('-', '_')}"
            password = pgb.generate_password()

        database = database.replace("-", "_")

        if not database:
            logger.warning("No database name provided")
            change_event.defer()
            return
        database = database.replace("-", "_")

        cfg = self.charm._read_pgb_config()

        self.charm._add_user(user, password, admin=False, cfg=cfg, render_cfg=False)

        pg_master_connstr = pgb.parse_kv_string_to_dict(cfg["databases"]["pg_master"])
        master_host = pg_master_connstr["host"]
        master_port = pg_master_connstr["port"],

        primary = str(
            ConnectionString(
                host=master_host,
                dbname=database,
                port=master_port,
                user=user,
                password=password,
                fallback_application_name=change_event.app.name,
            )
        )
        cfg["database"][database] = primary

        standbys = []
        for standby_name, standby_data in cfg["database"].items():
            # skip everything that's not a postgres standby.
            if standby_name[:21] is not "pgb_postgres_standby_":
                continue

            standby_idx = int(standby_name[21:])
            standby = str(
                ConnectionString(
                    host=standby_data["host"],
                    dbname=database,
                    port=standby_data["port"],
                    user=user,
                    password=password,
                    fallback_application_name=change_event.app.name,
                )
            )

            standbys.append(standby)
            cfg["databases"][f"{database}_standby_{standby_idx}"] = standby

        for databag in [app_databag, unit_databag]:
            databag["allowed-subnets"] = self.get_allowed_subnets(change_event.relation)
            databag["allowed-units"] = self.get_allowed_units(change_event.relation)
            databag["host"] = f"http://{master_host}"
            databag["master"] = primary
            databag["port"] = master_port
            databag["standbys"] = ",".join(standbys)
            databag["state"] = "master"
            databag["version"] = "12"
            databag["user"] = user
            databag["password"] = password
            databag["database"] = database

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """Handle db-relation-departed event.

        Removes relevant information from pgbouncer config when db relation is removed.

        This doesn't delete users or tables, following the design of the legacy charm.
        """
        if not self.charm.is_leader():
            return

        logger.info("db relation removed - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        app_databag = departed_event.relation.data[self.charm.app]

        cfg = self.charm._read_pgb_config()

        user = app_databag["user"]
        database = app_databag["database"]
        self.charm.remove_user(user, cfg=cfg, render_cfg = False)

        del cfg["database"][database]
        # Delete replicas
        # TODO find a smarter way of doing this
        for db in list(cfg["database"].keys()):
            if cfg["database"][db]["name"].contains(f"{database}_standby_"):
                del cfg["database"][db]

        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

