# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, Mock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import (
    BACKEND_RELATION_NAME,
    PEER_RELATION_NAME,
)


class TestPeers(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.app = self.charm.app.name
        self.unit = self.charm.unit.name
        self.harness.add_relation("upgrade", self.charm.app.name)

        self.rel_id = self.harness.add_relation(PEER_RELATION_NAME, self.charm.app.name)

    @patch("charm.PgBouncerCharm.configuration_check", return_value=True)
    @patch("charm.PgBouncerProvider.update_read_only_endpoints")
    @patch("charm.Peers._on_changed")
    def test_on_peers_joined(self, _on_changed, _update_read_only_endpoints, _configuration_check):
        with self.harness.hooks_disabled():
            self.harness.set_leader()

        event = Mock()
        self.charm.peers._on_joined(event)
        _on_changed.assert_called_once_with(event)
        _update_read_only_endpoints.assert_called_once_with()
        _update_read_only_endpoints.reset_mock()
        _on_changed.reset_mock()

        # Misconfiguration guard
        _configuration_check.return_value = False
        self.charm.peers._on_joined(event)
        _on_changed.assert_called_once_with(event)
        assert not _update_read_only_endpoints.called

    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.render_auth_file")
    @patch("charm.PgBouncerCharm.reload_pgbouncer")
    def test_on_peers_changed(self, reload_pgbouncer, render_auth_file, render_pgb_config):
        self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        self.charm.peers._on_changed(MagicMock())
        render_pgb_config.assert_called_once_with(reload_pgbouncer=True)
        render_pgb_config.reset_mock()
