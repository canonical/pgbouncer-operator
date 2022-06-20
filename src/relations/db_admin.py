# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres db-admin relation hooks & helpers.

This relation uses the pgsql interface.

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

TODO this is going to be a charm lib in the postgres charm later on, but for now we'll implement it here.
"""

import logging

from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase, RelationChangedEvent, RelationDepartedEvent
from ops.framework import Object

logger = logging.getLogger(__name__)

RELATION_ID = "db-admin"


# TODO check if we need DbAdminRequires in a charm lib.
class DbAdminProvides(Object):
    """Defines functionality for the 'requires' side of the 'backend-db-admin' relation.

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

        logger.info("database change detected - updating config")
        logger.info(
            "DEPRECATION WARNING - db-admin is a legacy relation, and will be deprecated in a future release. "
        )

        event_data = change_event.relation.data
        logger.info(event_data)
        pg_data = event_data[change_event.unit]

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
