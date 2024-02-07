#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

# TODO remove once data-integrator starts using the expose logic
import logging
from enum import Enum
from typing import Dict, MutableMapping, Optional

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseCreatedEvent,
    DatabaseRequires,
    DataRequires,
    IndexCreatedEvent,
    KafkaRequires,
    OpenSearchRequires,
    TopicCreatedEvent,
)
from literals import DATABASES, KAFKA, OPENSEARCH, PEER
from ops.charm import ActionEvent, CharmBase, RelationBrokenEvent, RelationEvent
from ops.framework import EventBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, StatusBase

logger = logging.getLogger(__name__)
Statuses = Enum("Statuses", ["ACTIVE", "BROKEN", "REMOVED"])


class IntegratorCharm(CharmBase):
    """Integrator charm that connects to database charms."""

    def _setup_database_requirer(self, relation_name: str) -> DatabaseRequires:
        """Handle the creation of relations and listeners."""
        database_requirer = DatabaseRequires(
            self,
            relation_name=relation_name,
            database_name=self.database_name or "",
            extra_user_roles=self.extra_user_roles or "",
            external_node_connectivity=True,
        )
        self.framework.observe(database_requirer.on.database_created, self._on_database_created)
        self.framework.observe(self.on[relation_name].relation_broken, self._on_relation_broken)
        return database_requirer

    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.get_credentials_action, self._on_get_credentials_action)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)

        self.framework.observe(self.on.update_status, self._on_update_status)

        # Databases: MySQL, PostgreSQL and MongoDB
        self.databases: Dict[str, DatabaseRequires] = {
            name: self._setup_database_requirer(name) for name in DATABASES
        }

        # Kafka
        self.kafka = KafkaRequires(
            self,
            relation_name=KAFKA,
            topic=self.topic_name or "",
            extra_user_roles=self.extra_user_roles or "",
            consumer_group_prefix=self.consumer_group_prefix or "",
        )
        self.framework.observe(self.kafka.on.topic_created, self._on_topic_created)
        self.framework.observe(self.on[KAFKA].relation_broken, self._on_relation_broken)

        # OpenSearch
        self.opensearch = OpenSearchRequires(
            self,
            relation_name=OPENSEARCH,
            index=self.index_name or "",
            extra_user_roles=self.extra_user_roles or "",
        )
        self.framework.observe(self.opensearch.on.index_created, self._on_index_created)
        self.framework.observe(self.on[OPENSEARCH].relation_broken, self._on_relation_broken)

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle relation broken event."""
        if not self.unit.is_leader():
            return
        # update peer databag to trigger the charm status update
        self._update_relation_status(event, Statuses.BROKEN.name)

    def get_status(self) -> StatusBase:
        """Return the current application status."""
        if not any([self.topic_name, self.database_name, self.index_name]):
            return BlockedStatus("Please specify either topic, index, or database name")

        if not any([self.is_database_related, self.is_kafka_related, self.is_opensearch_related]):
            return BlockedStatus("Please relate the data-integrator with the desired product")

        if self.is_kafka_related and self.topic_active != self.topic_name:
            logger.error(
                f"Trying to change Kafka configuration for existing relation : To change topic: {self.topic_active}, please remove relation and add it again"
            )
            return BlockedStatus(
                f"To change topic: {self.topic_active}, please remove relation and add it again"
            )

        if self.is_opensearch_related and self.index_active != self.index_name:
            logger.error(
                f"Trying to change OpenSearch configuration for existing relation : To change index name: {self.index_active}, please remove relation and add it again"
            )
            return BlockedStatus(
                f"To change index name: {self.index_active}, please remove relation and add it again"
            )

        if self.is_database_related and any(
            database != self.database_name for database in self.databases_active.values()
        ):
            current_database = list(self.databases_active.values())[0]
            logger.error(
                f"Trying to change database-name configuration for existing relation. To change database name: {current_database}, please remove relation and add it again"
            )
            return BlockedStatus(
                f"To change database name: {current_database}, please remove relation and add it again"
            )

        return ActiveStatus()

    def _on_update_status(self, _: EventBase) -> None:
        """Handle the status update."""
        self.unit.status = self.get_status()

    def _on_config_changed(self, _: EventBase) -> None:
        """Handle on config changed event."""
        # Only execute in the unit leader
        self.unit.status = self.get_status()

        if not self.unit.is_leader():
            return

        # update relation databag
        # if a relation has been created before configuring the topic or database name
        # update the relation databag with the proper value
        if not self.databases_active and self.database_name:
            database_relation_data = {
                "database": self.database_name,
                "extra-user-roles": self.extra_user_roles or "",
            }
            self._update_database_relations(database_relation_data)

        if not self.topic_active and self.topic_name:
            for rel in self.kafka.relations:
                self.kafka.update_relation_data(
                    rel.id,
                    {
                        "topic": self.topic_name or "",
                        "extra-user-roles": self.extra_user_roles or "",
                        "consumer-group-prefix": self.consumer_group_prefix or "",
                    },
                )

        if not self.index_active and self.index_name:
            for rel in self.opensearch.relations:
                self.opensearch.update_relation_data(
                    rel.id,
                    {
                        "index": self.index_name or "",
                        "extra-user-roles": self.extra_user_roles or "",
                    },
                )

    def _update_database_relations(self, database_relation_data: Dict[str, str]):
        """Update the relation data of the related databases."""
        for db_name, relation in self.database_relations.items():
            logger.debug(f"Updating databag for database: {db_name}")
            self.databases[db_name].update_relation_data(relation.id, database_relation_data)

    def _on_get_credentials_action(self, event: ActionEvent) -> None:
        """Returns the credentials an action response."""
        if not any([self.database_name, self.topic_name, self.index_name]):
            event.fail("The database name or topic name is not specified in the config.")
            event.set_results({"ok": False})
            return

        if not any([self.is_database_related, self.is_kafka_related, self.is_opensearch_related]):
            event.fail("The action can be run only after relation is created.")
            event.set_results({"ok": False})
            return

        result = {"ok": True}

        for name in self.databases_active.keys():
            result[name] = list(self.databases[name].fetch_relation_data().values())[0]

        if self.is_kafka_related:
            result[KAFKA] = list(self.kafka.fetch_relation_data().values())[0]

        if self.is_opensearch_related:
            result[OPENSEARCH] = list(self.opensearch.fetch_relation_data().values())[0]

        event.set_results(result)

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Event triggered when a database was created for this application."""
        logger.debug(f"Database credentials are received: {event.username}")
        self._on_config_changed(event)
        if not self.unit.is_leader():
            return
        # update values in the databag
        self._update_relation_status(event, Statuses.ACTIVE.name)

    def _on_topic_created(self, event: TopicCreatedEvent) -> None:
        """Event triggered when a topic was created for this application."""
        logger.debug(f"Kafka credentials are received: {event.username}")
        self._on_config_changed(event)
        if not self.unit.is_leader():
            return
        # update status of the relations in the peer-databag
        self._update_relation_status(event, Statuses.ACTIVE.name)

    def _on_index_created(self, event: IndexCreatedEvent) -> None:
        """Event triggered when an index is created for this application."""
        logger.debug(f"OpenSearch credentials are received: {event.username}")
        self._on_config_changed(event)
        if not self.unit.is_leader:
            return
        # update status of the relations in the peer-databag
        self._update_relation_status(event, Statuses.ACTIVE.name)

    def _update_relation_status(self, event: RelationEvent, status: str) -> None:
        """Update the relation status in the peer-relation databag."""
        self.set_secret("app", event.relation.name, status)

    def _on_peer_relation_changed(self, _: RelationEvent) -> None:
        """Handle the peer relation changed event."""
        if not self.unit.is_leader():
            return
        removed_relations = []
        # check for relation that has been removed
        for relation_data_key, relation_value in self.app_peer_data.items():
            if relation_value == Statuses.BROKEN.name:
                removed_relations.append(relation_data_key)
        if removed_relations:
            # update the unit status
            self.unit.status = self.get_status()
            # update relation status to removed if relation databag is empty
            for relation_name in removed_relations:
                # check if relation databag is not empty
                if self.model.relations[relation_name]:
                    continue
                self.set_secret("app", relation_name, Statuses.REMOVED.name)

    @property
    def database_name(self) -> Optional[str]:
        """Return the configured database name."""
        return self.model.config.get("database-name", None)

    @property
    def topic_name(self) -> Optional[str]:
        """Return the configured topic name."""
        return self.model.config.get("topic-name", None)

    @property
    def index_name(self) -> Optional[str]:
        """Return the configured database name."""
        return self.model.config.get("index-name", None)

    @property
    def extra_user_roles(self) -> Optional[str]:
        """Return the configured extra user roles."""
        return self.model.config.get("extra-user-roles", None)

    @property
    def consumer_group_prefix(self) -> Optional[str]:
        """Return the configured consumer group prefix."""
        return self.model.config.get("consumer-group-prefix", None)

    @property
    def database_relations(self) -> Dict[str, Relation]:
        """Return the active database relations."""
        return {
            name: requirer.relations[0]
            for name, requirer in self.databases.items()
            if len(requirer.relations)
        }

    @property
    def opensearch_relation(self) -> Optional[Relation]:
        """Return the opensearch relation if present."""
        return self.opensearch.relations[0] if len(self.opensearch.relations) else None

    @property
    def kafka_relation(self) -> Optional[Relation]:
        """Return the kafka relation if present."""
        return self.kafka.relations[0] if len(self.kafka.relations) else None

    @property
    def databases_active(self) -> Dict[str, str]:
        """Return the configured database name."""
        return {
            name: requirer.fetch_relation_field(requirer.relations[0].id, "database")
            for name, requirer in self.databases.items()
            if requirer.relations
            and requirer.fetch_relation_field(requirer.relations[0].id, "database")
        }

    @property
    def topic_active(self) -> Optional[str]:
        """Return the configured topic name."""
        if relation := self.kafka_relation:
            return self.kafka.fetch_relation_field(relation.id, "topic")

    @property
    def index_active(self) -> Optional[str]:
        """Return the configured index name."""
        if relation := self.opensearch_relation:
            return self.opensearch.fetch_relation_field(relation.id, "index")

    @property
    def extra_user_roles_active(self) -> Optional[str]:
        """Return the configured user-extra-roles parameter."""
        return (
            self.kafka.fetch_relation_field(relation.id, "extra-user-roles")
            if (relation := self.kafka_relation)
            else None
        )

    @property
    def is_database_related(self) -> bool:
        """Return if a relation with database is present."""
        possible_relations = [
            self._check_for_credentials(database_requirer)
            for _, database_requirer in self.databases.items()
        ]
        return any(possible_relations)

    @staticmethod
    def _check_for_credentials(requirer: DataRequires) -> bool:
        """Check if credentials are present in the relation databag."""
        for relation in requirer.relations:
            if requirer.fetch_relation_field(
                relation.id, "username"
            ) and requirer.fetch_relation_field(relation.id, "password"):
                return True
        return False

    @property
    def is_kafka_related(self) -> bool:
        """Return if a relation with kafka is present."""
        return self._check_for_credentials(self.kafka)

    @property
    def is_opensearch_related(self) -> bool:
        """Return if a relation with opensearch is present."""
        return self._check_for_credentials(self.opensearch)

    @property
    def app_peer_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        relation = self.model.get_relation(PEER)
        if not relation:
            return {}

        return relation.data[relation.app]

    @property
    def unit_peer_data(self) -> MutableMapping[str, str]:
        """Peer relation data object."""
        relation = self.model.get_relation(PEER)
        if relation is None:
            return {}

        return relation.data[self.unit]

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Set secret in the secret storage."""
        if scope == "unit":
            if not value:
                del self.unit_peer_data[key]
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")


if __name__ == "__main__":
    main(IntegratorCharm)
