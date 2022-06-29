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

TODO this relation is almost identical to db-admin - unify code.
"""

import logging
from typing import Iterable

from charms.pgbouncer_operator.v0 import pgb
from ops.charm import (
    CharmBase,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
)
from ops.framework import Object
from ops.model import Relation, Unit

from relations.backend_db_admin import STANDBY_PREFIX

logger = logging.getLogger(__name__)

RELATION_ID = "db"
STANDBY_PREFIX_LEN = len(STANDBY_PREFIX)


class DbProvides(Object):
    """Defines functionality for the 'requires' side of the 'db' relation.

    Hook events observed:
        - relation-changed
        - relation-departed
        - relation-broken
    """

    def __init__(self, charm: CharmBase):
        super().__init__(charm, RELATION_ID)

        self.framework.observe(charm.on[RELATION_ID].relation_changed, self._on_relation_changed)
        self.framework.observe(charm.on[RELATION_ID].relation_departed, self._on_relation_departed)
        self.framework.observe(charm.on[RELATION_ID].relation_broken, self._on_relation_broken)

        self.charm = charm

        # TODO consider making all the databag variables member variables of this object so they can be accessed outside of method scope.

    def _on_relation_changed(self, change_event: RelationChangedEvent):
        """Handle db-relation-changed event.

        Takes information from the db relation databag and copies it into the pgbouncer.ini
        config.
        """
        if not self.charm.unit.is_leader():
            return

        cfg = self.charm._read_pgb_config()
        dbs = cfg["databases"]

        if not dbs.get("pg_master"):
            # wait for backend_db_admin relation to populate config before we use it.
            logger.warning("waiting for backend-db-admin relation")
            change_event.defer()
            return

        logger.info(f"Setting up {change_event.relation.name} relation - updating config")
        logger.warning(
            "DEPRECATION WARNING - db is a legacy relation, and will be deprecated in a future release. "
        )

        unit_databag = change_event.relation.data[self.charm.unit]
        app_databag = change_event.relation.data[self.charm.app]

        # Check if app_databag is populated with relation data.
        if app_databag.get("user") is not None:
            database = unit_databag["database"]
            user = unit_databag["user"]
            password = unit_databag["password"]
        else:
            database = change_event.relation.data[change_event.unit].get("database")
            user = f"{RELATION_ID}_{change_event.relation.id}_{change_event.app.name.replace('-', '_')}"
            password = pgb.generate_password()

        if not database:
            logger.warning("No database name provided")
            change_event.defer()
            return

        database = database.replace("-", "_")

        # Get data about primary unit for databags and charm config.
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

        # Get data about standby units for databags and charm config.
        standbys = self._get_standbys(cfg, change_event, database, user, password)

        # Populate databags
        for databag in [app_databag, unit_databag]:
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

        unit_databag["state"] = self._get_state(standbys)

        # Write config data to charm filesystem
        self.charm.add_user(user, password, admin=False, cfg=cfg, render_cfg=False)
        self.charm._render_service_configs(cfg, reload_pgbouncer=True)

    def _get_postgres_standbys(self, cfg, event, database, user, password):
        dbs = cfg["databases"]

        standbys = ""
        for standby_name, standby_data in dict(dbs).items():
            # skip everything that's not a postgres standby, as defined by the backend-db-admin
            # relation
            if standby_name[:STANDBY_PREFIX_LEN] != STANDBY_PREFIX:
                continue

            standby_idx = standby_name[STANDBY_PREFIX_LEN:]
            standby = {
                "host": standby_data["host"],
                "dbname": database,
                "port": standby_data["port"],
                "user": user,
                "password": password,
                "fallback_application_name": event.app.name,
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
        if standbys is "":
            return "standalone"
        if self.charm.unit.is_leader:
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

        # All other changes are backend, and should be handled by the relation_changed handler that
        # fires after backend_relation_changed.
        for databag in [app_databag, unit_databag]:
            databag["allowed-subnets"] = self.get_allowed_subnets(departed_event.relation)

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
