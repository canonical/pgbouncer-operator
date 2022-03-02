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
        dbs = {
            "test": {"host": "test", "port": "4039", "dbname": "testdatabase"},
            "test2": {"host": "test2"},
        }
        admin_users = ["test_admin"]
        stats_users = ["test_admin", "test_stats"]
        listen_port = "4545"

        generated_ini = pgb.generate_pgbouncer_ini(
            dbs, admin_users=admin_users, stats_users=stats_users, listen_port=listen_port
        )
        expected_generated_ini = """[databases]
test = host=test port=4039 dbname=testdatabase
test2 = host=test2

[pgbouncer]
admin_users = test_admin
stats_users = test_admin,test_stats
listen_port = 4545

"""
        self.assertEqual(generated_ini, expected_generated_ini)

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

    def test_ini_parser__read(self):
        test_file = "tests/unit/data/test.ini"
        parser = pgb.IniParser()

        with open(test_file) as file:
            parser._read(file, "testfile")

        expected_parser_dbs = {
            "db": {
                "dbname": "test_db",
                "host": "test",
                "port": "10",
                "user": "test",
                "password": "test",
                "client_encoding": "test",
                "datestyle": "test",
                "timezone": "test",
                "pool_size": "test",
                "connect_query": "test",
            }
        }
        self.assertDictEqual(parser.dbs, expected_parser_dbs)
        expected_users = {"admin_users": ["Test"], "stats_users": ["Test", "stats_test"]}
        self.assertDictEqual(parser.users, expected_users)

        parser_output = parser.write_to_string()

        unmodded_file = ""
        with open(test_file) as f:
            for line in f.readlines():
                # Remove commented lines
                if line[0] not in ("#", ";"):
                    unmodded_file += line

        self.assertEqual(parser_output, unmodded_file)

    def test_ini_parser_read_dict(self):
        parser = pgb.IniParser()
        parser.read_dict(
            {
                "databases": {"db1": {"dbname": "test"}, "db2": {"host": "test_host"}},
                "pgbouncer": {
                    "admin_users": ["test"],
                    "stats_users": ["test", "stats_test"],
                },
            }
        )
        expected_dbs = {"db1": {"dbname": "test"}, "db2": {"host": "test_host"}}
        expected_users = {
            "admin_users": ["test"],
            "stats_users": ["test", "stats_test"],
        }
        self.assertDictEqual(parser.dbs, expected_dbs)
        self.assertDictEqual(parser.users, expected_users)

    def test_ini_parser_case_sensitive(self):
        parser = pgb.IniParser()
        self.assertEqual(parser.optionxform, str)
        parser.read_dict(
            {
                "databases": {
                    "db": {
                        "dbname": "test",
                        "port": "555",
                    },
                },
                "pgbouncer": {"admin_users": "CAPSTEST"},
            }
        )
        self.assertEqual(parser["pgbouncer"]["admin_users"], "CAPSTEST")

    def test_ini_parser_write_to_string(self):
        test_file = "tests/unit/data/test.ini"
        parser = pgb.IniParser()

        with open(test_file) as file:
            parser.read_file(file)
        parser_output = parser.write_to_string()

        unmodded_file = ""
        with open(test_file) as f:
            for line in f.readlines():
                # Remove commented lines
                if line[0] not in ("#", ";"):
                    unmodded_file += line

        self.assertEqual(parser_output, unmodded_file)
