# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pgbouncer pgb-peers relation hooks & helpers.

Example:
--------------------------------------------------------------------------------------------------------------------------------------------------------------
┃ relation (id: 2) ┃ pgbouncer                                                                                                                               ┃
--------------------------------------------------------------------------------------------------------------------------------------------------------------
│ relation name    │ pgb-peers                                                                                                                               │
│ interface        │ pgb_peers                                                                                                                               │
│ leader unit      │ 0                                                                                                                                       │
│ type             │ peer                                                                                                                                    │
--------------------------------------------------------------------------------------------------------------------------------------------------------------
│ application data │ ╭─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮ │
│                  │ │                                                                                                                                     │ │
│                  │ │  auth_file                            "pgbouncer_auth_relation_3" "md5a430a66f6761df1b5d1d608ed345e44f"                             │ │
│                  │ │  pgb_dbs_config   '{"1": {"name": "db_name", "legacy": false}}'                                                                     │ │
│                  │ │  leader                               10.180.162.4                                                                                  │ │
│                  │ │  pgbouncer_user_4_test_db_admin_3una  T6NX0iz1ZRHZF5kfYDanKM5z                                                                      │ │
│                  │ ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ unit data        │ ╭─ pgbouncer/0* ─╮ ╭─ pgbouncer/1 ─╮                                                                                                    │
│                  │ │ <empty>        │ │ <empty>       │                                                                                                    │
│                  │ ╰────────────────╯ ╰───────────────╯                                                                                                    │
--------------------------------------------------------------------------------------------------------------------------------------------------------------
"""  # noqa: W505

import logging
from typing import List, Optional, Set

from ops.charm import CharmBase, RelationChangedEvent, RelationCreatedEvent
from ops.framework import Object
from ops.model import Relation, Unit

from constants import PEER_RELATION_NAME

ADDRESS_KEY = "private-address"
LEADER_ADDRESS_KEY = "leader_ip"


logger = logging.getLogger(__name__)


class Peers(Object):
    """Defines functionality for the pgbouncer peer relation.

    The data created in this relation allows the pgbouncer charm to connect to the postgres charm.

    Hook events observed:
        - relation-created
        - relation-joined
        - relation-changed
    """

    def __init__(self, charm: CharmBase):
        super().__init__(charm, PEER_RELATION_NAME)

        self.charm = charm

        self.framework.observe(charm.on[PEER_RELATION_NAME].relation_created, self._on_created)
        self.framework.observe(charm.on[PEER_RELATION_NAME].relation_joined, self._on_changed)
        self.framework.observe(charm.on[PEER_RELATION_NAME].relation_changed, self._on_changed)
        self.framework.observe(charm.on.secret_changed, self._on_changed)
        self.framework.observe(charm.on.secret_remove, self._on_changed)
        self.framework.observe(charm.on[PEER_RELATION_NAME].relation_departed, self._on_departed)

    @property
    def relation(self) -> Relation:
        """Returns the relations in this model , or None if peer is not initialised."""
        return self.charm.model.get_relation(PEER_RELATION_NAME)

    @property
    def app_databag(self):
        """Returns the app databag for the Peer relation."""
        if not self.relation:
            return None
        return self.relation.data[self.charm.app]

    @property
    def unit_databag(self):
        """Returns this unit's databag for the Peer relation."""
        if not self.relation:
            return None
        return self.relation.data[self.charm.unit]

    @property
    def units_ips(self) -> Set[str]:
        """Fetch current set of peers IPs, not including the leader.

        Returns:
            A set of strings containing peers addresses, not including the leader.
        """
        units_ips = {self._get_unit_ip(unit) for unit in self.relation.units}
        units_ips.discard(None)
        units_ips.discard(self.leader_ip)
        units_ips.add(self.charm.unit_ip)
        return units_ips

    @property
    def leader_ip(self) -> str:
        """Gets the IP of the leader unit."""
        return self.app_databag.get(LEADER_ADDRESS_KEY, None)

    @property
    def units(self) -> List[Unit]:
        """Returns the peer relation units."""
        return self.relation.units

    def _get_unit_ip(self, unit: Unit) -> Optional[str]:
        """Get the IP address of a specific unit."""
        # Check if host is current host.
        if unit == self.charm.unit:
            return self.charm.unit_ip
        # Check if host is a peer.
        elif unit in self.relation.data:
            return str(self.relation.data[unit].get(ADDRESS_KEY))
        # Return None if the unit is not a peer neither the current unit.
        else:
            return None

    def _on_created(self, event: RelationCreatedEvent):
        if not self.charm.unit.is_leader():
            return

    def _on_changed(self, event: RelationChangedEvent):
        """If the current unit is a follower, write updated config and auth files to filesystem."""
        self.unit_databag.update({ADDRESS_KEY: self.charm.unit_ip})

        if self.charm.unit.is_leader():
            self.charm.update_client_connection_info()

            self.app_databag[LEADER_ADDRESS_KEY] = self.charm.unit_ip
            self.charm.generate_relation_databases()
            return

        if self.charm.backend.postgres:
            self.charm.render_prometheus_service()

        self.charm.render_pgb_config(reload_pgbouncer=True)

    def _on_departed(self, _):
        self.update_connection()

    def update_connection(self):
        """Updates available leader in app databag."""
        if self.charm.unit.is_leader():
            self.charm.update_client_connection_info()
            self.app_databag[LEADER_ADDRESS_KEY] = self.charm.unit_ip
