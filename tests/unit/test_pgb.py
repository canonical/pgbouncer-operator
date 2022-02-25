# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import string
import unittest

from lib.charms.dp_pgbouncer_operator.v0 import pgb


class TestPgb(unittest.TestCase):
    def test_generate_password(self):
        pw = pgb.generate_password()
        self.assertEqual(len(pw), 24)
        valid_chars = string.ascii_letters + string.digits
        for char in pw:
            assert char in valid_chars

    def test_generate_pgbouncer_ini(self):
        users = {"test1": "pw1", "test2": "pw2"}
        # Though this isn't correctly mocking an ops.model.ConfigData object, ConfigData implements
        # a LazyMapping under the hood that accesses variables in the same way as a dictionary -
        # they're effectively interchangeable in this context.
        config = {
            "pgb_databases": "test-dbs",
            "pgb_listen_port": "4454",
            "pgb_listen_address": "4.4.5.4",
        }
        pgb_ini = pgb.generate_pgbouncer_ini(users, config)
        expected_pgb_ini = pgb.PGB_INI.format(
            databases=config["pgb_databases"],
            listen_port=config["pgb_listen_port"],
            listen_addr=config["pgb_listen_address"],
            admin_users=",".join(users.keys()),
        )
        self.assertEqual(pgb_ini, expected_pgb_ini)

    def test_generate_userlist(self):
        users = {"test1": "pw1", "test2": "pw2"}
        userlist = pgb.generate_userlist(users)
        expected_userlist = '''"test1" "pw1"\n"test2" "pw2"'''
        self.assertEqual(userlist, expected_userlist)
        self.assertDictEqual(pgb.parse_userlist(expected_userlist), users)

    def test_parse_userlist(self):
        with open("tests/unit/data/test_userlist.txt") as f:
            userlist = f.read()
            users = pgb.parse_userlist(userlist)
            expected_users = {
                "testuser": "testpass",
                "another_testuser": "anotherpass",
                "1234": "",
                "": "",
            }
            self.assertDictEqual(users, expected_users)

            # Check that we can run input through a few times without anything getting corrupted.
            regen_userlist = pgb.generate_userlist(users)
            regen_users = pgb.parse_userlist(regen_userlist)
            self.assertNotEqual(regen_userlist, userlist)
            self.assertDictEqual(users, regen_users)
