# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import MagicMock, patch

from ops.testing import Harness

from charm import PgBouncerCharm
from constants import BACKEND_RELATION_NAME, PEER_RELATION_NAME
from lib.charms.pgbouncer_k8s.v0.pgb import DEFAULT_CONFIG, PgbConfig
from relations.peers import AUTH_FILE_DATABAG_KEY, CFG_FILE_DATABAG_KEY
from tests.helpers import patch_network_get


@patch_network_get(private_address="1.1.1.1")
class TestPeers(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

        self.charm = self.harness.charm
        self.app = self.charm.app.name
        self.unit = self.charm.unit.name

        self.rel_id = self.harness.add_relation(PEER_RELATION_NAME, self.charm.app.name)

    @patch("charm.PgBouncerCharm.render_pgb_config")
    @patch("charm.PgBouncerCharm.render_auth_file")
    @patch("charm.PgBouncerCharm.reload_pgbouncer")
    def test_on_peers_changed(self, reload_pgbouncer, render_auth_file, render_pgb_config):
        self.harness.add_relation(BACKEND_RELATION_NAME, "postgres")
        # We don't want to write anything if we're the leader
        self.harness.set_leader(True)
        self.charm.peers._on_changed(MagicMock())
        render_auth_file.assert_not_called()
        render_pgb_config.assert_not_called()
        reload_pgbouncer.assert_not_called()

        # Don't write anything if nothing is available to write
        self.harness.set_leader(False)
        self.charm.peers._on_changed(MagicMock())
        render_pgb_config.assert_not_called()
        render_auth_file.assert_not_called()
        reload_pgbouncer.assert_not_called()

        # Assert that we're reloading pgb even if we're only changing one thing
        with self.harness.hooks_disabled():
            self.harness.update_relation_data(
                self.rel_id,
                self.charm.app.name,
                {CFG_FILE_DATABAG_KEY: PgbConfig(DEFAULT_CONFIG).render()},
            )
        self.charm.peers._on_changed(MagicMock())
        render_pgb_config.assert_called_once()
        render_auth_file.assert_not_called()
        reload_pgbouncer.assert_called_once()
        render_pgb_config.reset_mock()
        reload_pgbouncer.reset_mock()

        with self.harness.hooks_disabled():
            self.harness.update_relation_data(
                self.rel_id, self.charm.app.name, {AUTH_FILE_DATABAG_KEY: '"user" "pass"'}
            )
        self.charm.peers._on_changed(MagicMock())
        render_pgb_config.assert_called_once()
        render_auth_file.assert_called_once()
        reload_pgbouncer.assert_called_once()
