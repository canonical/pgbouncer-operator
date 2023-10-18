# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest.mock import Mock, PropertyMock, patch

import pytest
import tenacity
from charms.data_platform_libs.v0.upgrade import ClusterNotReadyError
from ops.model import ActiveStatus, MaintenanceStatus
from ops.testing import Harness

from charm import PgBouncerCharm
from constants import SNAP_PACKAGES


class TestUpgrade(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.unit = self.harness.charm.unit

    @patch("charm.Peers.units", new_callable=PropertyMock)
    def test_build_upgrade_stack(self, _peers: Mock):
        _peers.return_value = [Mock(), Mock()]
        _peers.return_value[0].name = "test/1"
        _peers.return_value[1].name = "test/2"

        result = self.charm.upgrade.build_upgrade_stack()

        assert result == [0, 1, 2]

    @patch("upgrade.logger.info")
    def test_log_rollback_instructions(self, _logger: Mock):
        self.charm.upgrade.log_rollback_instructions()

        _logger.assert_called_once_with(
            "Run `juju refresh --revision <previous-revision> pgbouncer` to initiate the rollback"
        )

    @patch("charm.BackendDatabaseRequires.postgres", return_value=True, new_callable=PropertyMock)
    @patch("charm.PgbouncerUpgrade.on_upgrade_changed")
    @patch("charm.PgbouncerUpgrade.set_unit_completed")
    @patch("charm.PgbouncerUpgrade._cluster_checks")
    @patch("charm.PgBouncerCharm.render_prometheus_service")
    @patch("charm.PgBouncerCharm.reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_utility_files")
    @patch("charm.PgBouncerCharm._install_snap_packages")
    @patch("charm.PgBouncerCharm.remove_exporter_service")
    @patch("upgrade.systemd")
    def test_on_upgrade_granted(
        self,
        _systemd: Mock,
        _remove_exporter_service: Mock,
        _install_snap_packages: Mock,
        _render_utility_files: Mock,
        _reload_pgbouncer: Mock,
        _render_prometheus_service: Mock,
        _cluster_checks: Mock,
        _set_unit_completed: Mock,
        _on_upgrade_changed: Mock,
        _,
    ):
        event = Mock()

        self.charm.upgrade._on_upgrade_granted(event)

        assert _systemd.service_stop.call_count == len(self.charm.pgb_services)
        for svc in self.charm.pgb_services:
            _systemd.service_stop.assert_any_call(svc)
        _remove_exporter_service.assert_called_once_with()
        _install_snap_packages.assert_called_once_with(packages=SNAP_PACKAGES, refresh=True)
        _render_prometheus_service.assert_called_once_with()
        _cluster_checks.assert_called_once_with()
        _set_unit_completed.assert_called_once_with()

        # Test extra call as leader
        with self.harness.hooks_disabled():
            self.harness.set_leader(True)

        self.charm.upgrade._on_upgrade_granted(event)

        _on_upgrade_changed.assert_called_once_with(event)

    @patch("upgrade.wait_fixed", return_value=tenacity.wait_fixed(0))
    @patch("charm.BackendDatabaseRequires.postgres", return_value=True, new_callable=PropertyMock)
    @patch("charm.PgbouncerUpgrade.on_upgrade_changed")
    @patch("charm.PgbouncerUpgrade.set_unit_completed")
    @patch("charm.PgbouncerUpgrade._cluster_checks")
    @patch("charm.PgBouncerCharm.render_prometheus_service")
    @patch("charm.PgBouncerCharm.reload_pgbouncer")
    @patch("charm.PgBouncerCharm.render_utility_files")
    @patch("charm.PgBouncerCharm._install_snap_packages")
    @patch("charm.PgBouncerCharm.remove_exporter_service")
    @patch("upgrade.systemd")
    def test_on_upgrade_granted_error(
        self,
        _systemd: Mock,
        _remove_exporter_service: Mock,
        _install_snap_packages: Mock,
        _render_utility_files: Mock,
        _reload_pgbouncer: Mock,
        _render_prometheus_service: Mock,
        _cluster_checks: Mock,
        _set_unit_completed: Mock,
        _on_upgrade_changed: Mock,
        _,
        __,
    ):
        _cluster_checks.side_effect = ClusterNotReadyError("test", "test")

        with pytest.raises(ClusterNotReadyError):
            self.charm.upgrade._on_upgrade_granted(Mock())

    @patch("charm.PgBouncerCharm.check_status", return_value=ActiveStatus())
    def test_pre_upgrade_check(self, _check_status: Mock):
        self.charm.upgrade.pre_upgrade_check()

        _check_status.assert_called_once_with()

    @patch("charm.PgBouncerCharm.check_status", return_value=MaintenanceStatus())
    def test_pre_upgrade_check_not_ready(self, _check_status: Mock):
        with pytest.raises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

        _check_status.assert_called_once_with()

    @patch("charm.BackendDatabaseRequires.postgres", return_value=True, new_callable=PropertyMock)
    @patch("charm.BackendDatabaseRequires.ready", return_value=False, new_callable=PropertyMock)
    @patch("charm.PgBouncerCharm.check_status", return_value=ActiveStatus())
    def test_pre_upgrade_check_backend_not_ready(self, _check_status: Mock, _, __):
        print(self.charm.backend.ready)
        with pytest.raises(ClusterNotReadyError):
            self.charm.upgrade.pre_upgrade_check()

        _check_status.assert_called_once_with()
