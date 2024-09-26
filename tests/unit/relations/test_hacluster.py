# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from ipaddress import IPv4Address, IPv6Address
from unittest import TestCase
from unittest.mock import Mock, PropertyMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import HACLUSTER_RELATION_NAME


class TestHaCluster(TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.app = self.charm.app.name
        self.unit = self.charm.unit.name
        self.harness.add_relation("upgrade", self.charm.app.name)

        self.rel_id = self.harness.add_relation(HACLUSTER_RELATION_NAME, self.charm.app.name)

    def test_is_clustered(self):
        # No remote
        assert not self.charm.hacluster._is_clustered()

        # Not clustered
        with self.harness.hooks_disabled():
            self.harness.add_relation_unit(self.rel_id, "hacluster/0")
            self.harness.update_relation_data(self.rel_id, "hacluster/0", {})

        assert not self.charm.hacluster._is_clustered()

        # Valid clustered
        with self.harness.hooks_disabled():
            self.harness.update_relation_data(self.rel_id, "hacluster/0", {"clustered": "yes"})

        assert self.charm.hacluster._is_clustered()

    @patch("charm.PgBouncerCharm.configuration_check", return_value=False)
    @patch("charm.HaCluster.set_vip", return_value=True)
    def test_on_changed(self, _set_vip, _configuration_check):
        # Defer on invalid configuration
        event = Mock()
        self.charm.hacluster._on_changed(event)

        event.defer.assert_called_once_with()
        assert not _set_vip.called

        _configuration_check.return_value = True
        with self.harness.hooks_disabled():
            self.harness.update_config({"vip": "1.2.3.4"})

        self.charm.hacluster._on_changed(Mock())

        _set_vip.assert_called_once_with(IPv4Address("1.2.3.4"))

    @patch("charm.HaCluster._is_clustered", return_value=False)
    @patch("charm.HaCluster.relation", new_callable=PropertyMock, return_value=False)
    def test_set_vip_no_relation(self, _relation, _is_clustered):
        # Not rel
        self.charm.hacluster.set_vip(IPv4Address("1.2.3.4"))

        assert not _is_clustered.called

    @patch("charm.HaCluster._is_clustered", return_value=False)
    def test_set_vip(self, _is_clustered):
        # Not clustered
        self.charm.hacluster.set_vip(IPv4Address("1.2.3.4"))
        assert self.harness.get_relation_data(self.rel_id, self.charm.unit) == {}

        # ipv4 address
        _is_clustered.return_value = True

        self.charm.hacluster.set_vip(IPv4Address("1.2.3.4"))

        assert self.harness.get_relation_data(self.rel_id, self.charm.unit) == {
            "json_resource_params": '{"res_pgbouncer_d716ce1885885a_vip": " params '
            'ip=\\"1.2.3.4\\" meta '
            'migration-threshold=\\"INFINITY\\" '
            'failure-timeout=\\"5s\\" op monitor '
            'timeout=\\"20s\\" interval=\\"10s\\" depth=\\"0\\""}',
            "json_resources": '{"res_pgbouncer_d716ce1885885a_vip": ' '"ocf:heartbeat:IPaddr2"}',
        }

        # ipv6 address
        self.charm.hacluster.set_vip(IPv6Address("::1"))

        assert self.harness.get_relation_data(self.rel_id, self.charm.unit) == {
            "json_resource_params": '{"res_pgbouncer_61b6532057c944_vip": " params '
            'ipv6addr=\\"::1\\" meta '
            'migration-threshold=\\"INFINITY\\" '
            'failure-timeout=\\"5s\\" op monitor '
            'timeout=\\"20s\\" interval=\\"10s\\" depth=\\"0\\""}',
            "json_resources": '{"res_pgbouncer_61b6532057c944_vip": ' '"ocf:heartbeat:IPv6addr"}',
        }

        # unset data
        self.charm.hacluster.set_vip("")
        assert self.harness.get_relation_data(self.rel_id, self.charm.unit) == {
            "json_resource_params": "{}",
            "json_resources": "{}",
        }
