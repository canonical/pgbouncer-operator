# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness

from charm import PgBouncerCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PgBouncerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_on_install(self):
        pass

    def test_on_config_changed(self):
        pass

    def test_install_apt_packages(self):
        pass

    def test_push_container_config(self):
        pass

    def test_push_pgbouncer_ini(self):
        pass

    def test_push_userlist(self):
        pass

    def test_get_userlist_from_machine(self):
        pass
