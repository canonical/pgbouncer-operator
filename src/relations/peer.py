# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Postgres backend-db-admin relation hooks & helpers.
This relation uses the pgsql interface.
Some example relation data is below. The only parts of this we actually need are the "master" and
"standbys" fields. All values are examples taken from a test deployment, and are not definite.
Example with 2 postgresql instances:
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ category  ┃            keys ┃ pgbouncer-operator/23 ┃ postgresql/4                          ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ metadata  │        endpoint │ 'backend-db-admin'    │ 'db-admin'                            │
│           │          leader │ True                  │ True                                  │
├───────────┼─────────────────┼───────────────────────┼───────────────────────────────────────┤
│ unit data │ allowed-subnets │                       │ 10.101.233.152/32                     │
│           │   allowed-units │                       │ pgbouncer-operator/23                 │
│           │        database │                       │ pgbouncer-operator                    │
│           │            host │                       │ 10.101.233.241                        │
│           │          master │                       │ dbname=pgbouncer-operator             │
│           │                 │                       │ host=10.101.233.241                   │
│           │                 │                       │ password=zWRHxMgqZBPcLPh5VXCfGyjJj4c7 │
│           │                 │                       │ cP2qjnwdj port=5432                   │
│           │                 │                       │ user=jujuadmin_pgbouncer-operator     │
│           │        password │                       │ zWRHxMgqZBPcLPh5VXCfGyjJj4c7cP2qjnwdj │
│           │            port │                       │ 5432                                  │
│           │        standbys │                       │ dbname=pgbouncer-operator             │
│           │                 │                       │ host=10.101.233.169                   │
│           │                 │                       │ password=zWRHxMgqZBPcLPh5VXCfGyjJj4c7 │
│           │                 │                       │ cP2qjnwdj port=5432                   │
│           │                 │                       │ user=jujuadmin_pgbouncer-operator     │
│           │           state │                       │ master                                │
│           │            user │                       │ jujuadmin_pgbouncer-operator          │
│           │         version │                       │ 12                                    │
└───────────┴─────────────────┴───────────────────────┴───────────────────────────────────────┘
If there were multiple standbys, they would be separated by a newline character.
Example with 1 postgresql instance:
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ category  ┃            keys ┃ pgbouncer-operator/23 ┃ postgresql/4                          ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ metadata  │        endpoint │ 'backend-db-admin'    │ 'db-admin'                            │
│           │          leader │ True                  │ True                                  │
├───────────┼─────────────────┼───────────────────────┼───────────────────────────────────────┤
│ unit data │ allowed-subnets │                       │ 10.101.233.152/32                     │
│           │   allowed-units │                       │ pgbouncer-operator/23                 │
│           │        database │                       │ pgbouncer-operator                    │
│           │            host │                       │ 10.101.233.241                        │
│           │          master │                       │ dbname=pgbouncer-operator             │
│           │                 │                       │ host=10.101.233.241                   │
│           │                 │                       │ password=zWRHxMgqZBPcLPh5VXCfGyjJj4c7 │
│           │                 │                       │ cP2qjnwdj port=5432                   │
│           │                 │                       │ user=jujuadmin_pgbouncer-operator     │
│           │        password │                       │ zWRHxMgqZBPcLPh5VXCfGyjJj4c7cP2qjnwdj │
│           │            port │                       │ 5432                                  │
│           │           state │                       │ standalone                            │
│           │            user │                       │ jujuadmin_pgbouncer-operator          │
│           │         version │                       │ 12                                    │
└───────────┴─────────────────┴───────────────────────┴───────────────────────────────────────┘
"""

import logging

from charms.pgbouncer_operator.v0 import pgb
from ops.charm import CharmBase, RelationChangedEvent, RelationDepartedEvent, LeaderElectedEvent
from ops.framework import Object
from ops.model import Unit

logger = logging.getLogger(__name__)

PEER_RELATION_ID = "pgbouncer-replicas"


class PgbPeer(Object):
    """Defines functionality for the pgbouncer peer relation event
    Hook events observed:
        - leader-elected
        - relation-changed
        - relation-departed
    """

    def __init__(self, charm: CharmBase):
        super().__init__(charm, PEER_RELATION_ID)

        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(charm.on[PEER_RELATION_ID].relation_changed, self._on_relation_changed)
        self.framework.observe(charm.on[PEER_RELATION_ID].relation_departed, self._on_relation_departed)

        self.charm = charm

    def _on_leader_elected(self, elected_event: LeaderElectedEvent):
        """"""

    def _on_relation_changed(self, changed_event: RelationChangedEvent):
        """"""

    def _on_relation_departed(self, departed_event: RelationDepartedEvent):
        """"""