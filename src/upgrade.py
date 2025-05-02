# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrades implementation."""

import json
import logging
import os
from typing import List

import psycopg2
from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    UpgradeGrantedEvent,
)
from charms.operator_libs_linux.v1 import systemd
from charms.pgbouncer_k8s.v0.pgb import generate_password
from ops.model import MaintenanceStatus
from pydantic import BaseModel
from tenacity import Retrying, stop_after_attempt, wait_fixed
from typing_extensions import override

from constants import APP_SCOPE, AUTH_FILE_DATABAG_KEY, MONITORING_PASSWORD_KEY, PGB, SNAP_PACKAGES

DEFAULT_MESSAGE = "Pre-upgrade check failed and cannot safely upgrade"

logger = logging.getLogger(__name__)


class PgbouncerDependencyModel(BaseModel):
    """Pgbouncer dependencies model."""

    charm: DependencyModel
    snap: DependencyModel


def get_pgbouncer_dependencies_model() -> PgbouncerDependencyModel:
    """Return the PostgreSQL dependencies model."""
    with open("src/dependency.json") as dependency_file:
        _deps = json.load(dependency_file)
    return PgbouncerDependencyModel(**_deps)


class PgbouncerUpgrade(DataUpgrade):
    """PostgreSQL upgrade class."""

    def __init__(self, charm, model: BaseModel, **kwargs) -> None:
        """Initialize the class."""
        super().__init__(charm, model, **kwargs)
        self.charm = charm

    @override
    def build_upgrade_stack(self) -> List[int]:
        """Builds ordered iterable of all application unit.ids to upgrade in."""
        return [
            int(unit.name.split("/")[-1])
            for unit in [self.charm.unit, *list(self.charm.peers.units)]
        ]

    @override
    def log_rollback_instructions(self) -> None:
        """Log rollback instructions."""
        logger.info(
            "Run `juju refresh --revision <previous-revision> pgbouncer` to initiate the rollback"
        )

    def _cluster_checks(self) -> None:
        """Check that the cluster is in healthy state."""
        if not self.charm.check_pgb_running():
            raise ClusterNotReadyError(DEFAULT_MESSAGE, "Not all pgbouncer services are up yet.")

        if self.charm.backend.postgres and not self.charm.backend.ready:
            raise ClusterNotReadyError(DEFAULT_MESSAGE, "Backend relation is still initialising.")

    def _handle_md5_monitoring_auth(self) -> None:
        if not self.charm.unit.is_leader() or not (
            auth_file := self.charm.get_secret(APP_SCOPE, AUTH_FILE_DATABAG_KEY)
        ):
            return

        monitoring_prefix = f'"{self.charm.backend.stats_user}" "md5'
        # Regenerate monitoring user if it is still md5
        new_auth = []
        for line in auth_file.split("\n"):
            if line.startswith(monitoring_prefix):
                stats_password = self.charm.get_secret(APP_SCOPE, MONITORING_PASSWORD_KEY)
                try:
                    hashed_monitoring_password = self.charm.backend.generate_monitoring_hash(
                        stats_password
                    )
                except psycopg2.Error:
                    logger.error(
                        "Cannot generate SCRAM monitoring password. Keeping existing MD5 hash"
                    )
                    return
                new_auth.append(
                    f'"{self.charm.backend.stats_user}" "{hashed_monitoring_password}"'
                )
            else:
                new_auth.append(line)
        new_auth_file = "\n".join(new_auth)
        if new_auth_file != auth_file:
            self.charm.set_secret(APP_SCOPE, AUTH_FILE_DATABAG_KEY, new_auth_file)

    @override
    def _on_upgrade_granted(self, event: UpgradeGrantedEvent) -> None:
        # Refresh the charmed PostgreSQL snap and restart the database.
        self.charm.unit.status = MaintenanceStatus("stopping services")
        # If pgb is upgraded from a version that only uses cpu count excess services should be stopped
        for service in [f"{PGB}-{self.charm.app.name}@{i}" for i in range(os.cpu_count())]:
            if systemd.service_running(service):
                systemd.service_stop(service)
        if self.charm.backend.postgres:
            self.charm.remove_exporter_service()

        self.charm.unit.status = MaintenanceStatus("refreshing the snap")
        self.charm._install_snap_packages(packages=SNAP_PACKAGES, refresh=True)

        self.charm.unit.status = MaintenanceStatus("restarting services")
        if self.charm.unit.is_leader():
            self.charm.generate_relation_databases()
        self._handle_md5_monitoring_auth()
        if not self.charm.peers.unit_databag.get("userlist_nonce"):
            self.charm.peers.unit_databag["userlist_nonce"] = generate_password()

        self.charm.create_instance_directories()
        self.charm.render_auth_file()

        self.charm.render_utility_files()
        self.charm.render_pgb_config()
        if self.charm.backend.postgres:
            self.charm.render_prometheus_service()

        for attempt in Retrying(stop=stop_after_attempt(6), wait=wait_fixed(10), reraise=True):
            with attempt:
                self._cluster_checks()

        self.set_unit_completed()
        self.charm.update_status()

        # Ensures leader gets its own relation-changed when it upgrades
        if self.charm.unit.is_leader():
            self.on_upgrade_changed(event)

    @override
    def pre_upgrade_check(self) -> None:
        """Runs necessary checks validating the cluster is in a healthy state to upgrade.

        Called by all units during :meth:`_on_pre_upgrade_check_action`.

        Raises:
            :class:`ClusterNotReadyError`: if cluster is not ready to upgrade
        """
        self._cluster_checks()
