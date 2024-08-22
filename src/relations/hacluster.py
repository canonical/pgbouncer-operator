# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""hacluster relation hooks and helpers."""

import json
import logging
from hashlib import shake_128
from ipaddress import IPv4Address, IPv6Address
from typing import Optional, Union

from ops import CharmBase, Object, Relation, RelationChangedEvent, Unit

from constants import HACLUSTER_RELATION_NAME

logger = logging.getLogger(__name__)


class HaCluster(Object):
    """Defines hacluster functunality."""

    def __init__(self, charm: CharmBase):
        super().__init__(charm, HACLUSTER_RELATION_NAME)

        self.charm = charm

        self.framework.observe(
            charm.on[HACLUSTER_RELATION_NAME].relation_changed, self._on_changed
        )

    @property
    def relation(self) -> Relation:
        """Returns the relations in this model, or None if hacluster is not initialised."""
        return self.charm.model.get_relation(HACLUSTER_RELATION_NAME)

    def _is_clustered(self) -> bool:
        for key, value in self.relation.data.items():
            if isinstance(key, Unit) and key != self.charm.unit:
                if value.get("clustered") in ("yes", "true"):
                    return True
                break
        return False

    def _on_changed(self, event: RelationChangedEvent) -> None:
        self.set_vip(self.charm.config.vip)

    def set_vip(self, vip: Optional[Union[IPv4Address, IPv6Address]]) -> None:
        """Adds the requested virtual IP to the integration."""
        if not self.relation:
            return

        if not self._is_clustered():
            logger.debug("early exit set_vip: ha relation not yet clustered")
            return

        if vip:
            # TODO Add nic support
            vip_key = f"res_{self.charm.app.name}_{shake_128(str(vip).encode()).hexdigest(7)}_vip"
            vip_params = " params"
            if isinstance(vip, IPv4Address):
                vip_resources = "ocf:heartbeat:IPaddr2"
                vip_params += f' ip="{vip}"'
            else:
                vip_resources = "ocf:heartbeat:IPv6addr"
                vip_params += f' ipv6addr="{vip}"'

            # Monitor the VIP
            vip_params += ' meta migration-threshold="INFINITY" failure-timeout="5s"'
            vip_params += ' op monitor timeout="20s" interval="10s" depth="0"'
            json_resources = json.dumps({vip_key: vip_resources})
            json_resource_params = json.dumps({vip_key: vip_params})

        else:
            json_resources = "{}"
            json_resource_params = "{}"

        self.relation.data[self.charm.unit].update({
            "json_resources": json_resources,
            "json_resource_params": json_resource_params,
        })
        self.charm.update_status()
