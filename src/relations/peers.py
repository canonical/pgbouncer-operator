# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Pgbouncer pgb-peers relation hooks & helpers.

Example:
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ relation (id: 2) ┃ pgbouncer                                                                                    ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ relation name    │ pgb-peers                                                                                    │
│ interface        │ pgb-peers                                                                                    │
│ leader unit      │ 2                                                                                            │
│ type             │ peer                                                                                         │
├──────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ application data │ ╭──────────────────────────────────────────────────────────────────────────────────────────╮ │
│                  │ │                                                                                          │ │
│                  │ │  auth_file                      "pgbouncer_auth_relation_3"                              │ │
│                  │ │                                 "md516ce6352db3bc84cd8e3900a4eee8302"                    │ │
│                  │ │  cfg_file                                                                                │ │
│                  │ │                                 mailman3 = host=10.180.162.236 dbname=mailman3 port=5432 │ │
│                  │ │                                 auth_user=pgbouncer_auth_relation_3                      │ │
│                  │ │                                                                                          │ │
│                  │ │                                                                                          │ │
│                  │ │                                 listen_addr = *                                          │ │
│                  │ │                                 listen_port = 5432                                       │ │
│                  │ │                                 logfile = /var/lib/postgresql/pgbouncer/pgbouncer.log    │ │
│                  │ │                                 pidfile = /var/lib/postgresql/pgbouncer/pgbouncer.pid    │ │
│                  │ │                                 admin_users =                                            │ │
│                  │ │                                 stats_users =                                            │ │
│                  │ │                                 auth_type = md5                                          │ │
│                  │ │                                 user = postgres                                          │ │
│                  │ │                                 max_client_conn = 10000                                  │ │
│                  │ │                                 ignore_startup_parameters = extra_float_digits           │ │
│                  │ │                                 so_reuseport = 1                                         │ │
│                  │ │                                 unix_socket_dir = /var/lib/postgresql/pgbouncer          │ │
│                  │ │                                 pool_mode = session                                      │ │
│                  │ │                                 max_db_connections = 100                                 │ │
│                  │ │                                 default_pool_size = 13                                   │ │
│                  │ │                                 min_pool_size = 7                                        │ │
│                  │ │                                 reserve_pool_size = 7                                    │ │
│                  │ │                                 auth_file = /var/lib/postgresql/pgbouncer/userlist.txt   │ │
│                  │ │                                                                                          │ │
│                  │ │                                                                                          │ │
│                  │ │  pgbouncer_user_4_test_db_pccj  bRRJhvjPzwAbCboQuMJ3JtEc                                 │ │
│                  │ ╰──────────────────────────────────────────────────────────────────────────────────────────╯ │
│ unit data        │ ╭─ pgbouncer/1 ─╮ ╭─ pgbouncer/2* ─╮                                                         │
│                  │ │ <empty>       │ │ <empty>        │                                                         │
│                  │ ╰───────────────╯ ╰────────────────╯                                                         │
└──────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────┘
"""  # noqa: W505

import logging
from typing import Optional, Set

from charms.pgbouncer_k8s.v0.pgb import PgbConfig
from ops.charm import CharmBase, RelationChangedEvent, RelationCreatedEvent
from ops.framework import Object
from ops.model import Unit
from ops.pebble import ConnectionError

from constants import PEER_RELATION_NAME

CFG_FILE_DATABAG_KEY = "cfg_file"
AUTH_FILE_DATABAG_KEY = "auth_file"
ADDRESS_KEY = "private-address"


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

    @property
    def relation(self):
        """Returns the relations in this model , or None if peer is not initialised."""
        return self.model.get_relation(PEER_RELATION_NAME, None)

    @property
    def app_databag(self):
        """Returns the app databag for the Peer relation."""
        if not self.relation:
            return None
        return self.relation.data[self.charm.app]

    @property
    def unit_databag(self):
        """Returns the unit databag for the Peer relation."""
        if not self.relation:
            return None
        return self.relation.data[self.charm.unit]

    @property
    def units_ips(self) -> Set[str]:
        """Fetch current list of peers IPs.
        Returns:
            A list of peers addresses (strings).
        """
        # Get all members IPs and remove the current unit IP from the list.
        addresses = {self._get_unit_ip(unit) for unit in self.relation.units}
        addresses.add(self._unit_ip)
        return addresses

    @property
    def leader_ip(self) -> str:
        """gets the IP of the leader unit."""
        return self.app_databag.get("leader", None)

    def _get_unit_ip(self, unit: Unit) -> Optional[str]:
        """Get the IP address of a specific unit."""
        # Check if host is current host.
        if unit == self.unit:
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

        try:
            cfg = self.charm.read_pgb_config()
            self.update_cfg(cfg)
        except FileNotFoundError:
            # If there's no config, the charm start hook hasn't fired yet, so defer until it's
            # available.
            event.defer()
            return

        if self.charm.backend.postgres:
            # The backend relation creates the userlist, so only upload userlist to databag if
            # backend relation is initialised. If not, it'll be added when that relation first
            # writes it to the filesystem, so no need to add it now.
            self.update_auth_file(self.charm.read_auth_file())

    def _on_changed(self, event: RelationChangedEvent):
        """If the current unit is a follower, write updated config and auth files to filesystem."""
        logger.error(self.charm.unit_ip)
        self.unit_databag[ADDRESS_KEY] = self.charm.unit_ip

        if self.charm.unit.is_leader():
            try:
                cfg = self.charm.read_pgb_config()
            except FileNotFoundError:
                # If there's no config, the charm start hook hasn't fired yet, so defer until it's
                # available.
                event.defer()
                return

            self.update_cfg(cfg)
            self.app_databag["leader"] = self.charm.unit_ip
            return

        if cfg := self.get_secret("app", CFG_FILE_DATABAG_KEY):
            self.charm.render_pgb_config(PgbConfig(cfg))

        if auth_file := self.get_secret("app", AUTH_FILE_DATABAG_KEY):
            self.charm.render_auth_file(auth_file)

        if cfg is not None or auth_file is not None:
            try:
                # raises an error if this is fired before on_pebble_ready.
                self.charm.reload_pgbouncer()
            except ConnectionError:
                event.defer()

    def set_secret(self, scope: str, key: str, value: str):
        """Sets secret value.

        Placeholder method for Juju Secrets interface.

        Args:
            scope: scope for data. Can be "unit" or "app".
            key: key to set value to
            value: value to be set
        """
        if scope == "unit":
            if not value:
                self.unit_databag.pop(key, None)
                return
            self.unit_databag.update({key: value})
        elif scope == "app":
            if not value:
                self.app_databag.pop(key, None)
                return
            self.app_databag.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")

    def del_secret(self, scope: str, key: str):
        """Deletes secret value.

        Placeholder method for Juju Secrets interface.

        Args:
            scope: scope for data. Can be "unit" or "app".
            key: key to access data
        """
        if scope == "unit":
            self.unit_databag.pop(key, None)
            return
        elif scope == "app":
            self.app_databag.pop(key, None)
            return
        else:
            raise RuntimeError("Unknown secret scope.")

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Gets secret value.

        Placeholder method for Juju Secrets interface.

        Args:
            scope: scope for data. Can be "unit" or "app".
            key: key to access data

        Returns:
            value at `key` in `scope` databag.
        """
        if scope == "unit":
            return self.unit_databag.get(key, None)
        elif scope == "app":
            return self.app_databag.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def update_cfg(self, cfg: PgbConfig) -> None:
        """Writes cfg to app databag if leader."""
        if not self.charm.unit.is_leader() or not self.relation:
            return

        self.set_secret("app", CFG_FILE_DATABAG_KEY, cfg.render())
        logger.debug("updated config file in peer databag")

    def get_cfg(self) -> PgbConfig:
        """Retrieves the pgbouncer config from the peer databag."""
        if cfg := self.get_secret("app", CFG_FILE_DATABAG_KEY):
            return PgbConfig(cfg)
        else:
            return None

    def update_auth_file(self, auth_file: str) -> None:
        """Writes auth_file to app databag if leader."""
        if not self.charm.unit.is_leader() or not self.relation:
            return

        self.set_secret("app", AUTH_FILE_DATABAG_KEY, auth_file)
        logger.debug("updated auth file in peer databag")

    def add_user(self, username: str, password: str):
        """Adds user to app databag."""
        if not self.charm.unit.is_leader():
            return

        self.set_secret("app", username, password)

    def remove_user(self, username: str):
        """Removes user from app databag."""
        if not self.charm.unit.is_leader():
            return

        self.del_secret("app", username)
