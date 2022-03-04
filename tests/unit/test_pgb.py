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
        pgbouncer = {
            "admin_users": admin_users,
            "stats_users": stats_users,
            "listen_port": listen_port,
        }

        generated_ini = pgb.generate_pgbouncer_ini(databases=dbs, pgbouncer=pgbouncer)
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

    def test_pgb_ini_parse_string(self):
        input_string = """[databases]
test = host=test port=4039 dbname=testdatabase
test2 = host=test2

[pgbouncer]
admin_users = test_admin
stats_users = test_admin,test_stats
listen_port = 4545

"""
        ini = pgb.PgbIni()
        ini.parse_string(input_string)
        expected_dict = {"host": "test", "port": "4039", "dbname": "testdatabase"}
        self.assertDictEqual(ini["databases"]["test"], expected_dict)
        self.assertEqual(ini["pgbouncer"]["stats_users"], ["test_admin", "test_stats"])

    def test_pgb_ini_parse_dict(self):
        input_dict = {
            "databases": {
                "db1": {"dbname": "test"},
                "db2": {"host": "test_host"},
            },
            "pgbouncer": {
                "logfile": "/etc/pgbouncer/pgb.log",
                "admin_users": ["test"],
                "stats_users": ["test", "stats_test"],
            },
            "users": {
                "test": {"pool_mode": "session", "max_user_connections": "22"},
            },
        }
        ini = pgb.PgbIni()
        ini.parse_dict(input_dict)
        self.assertDictEqual(input_dict, dict(ini))

    def test_pgb_ini_render(self):
        input_string = """[databases]
test = host=test port=4039 dbname=testdatabase
test2 = host=test2

[pgbouncer]
admin_users = test_admin
stats_users = test_admin,test_stats
listen_port = 4545

"""
        ini = pgb.PgbIni()
        ini.parse_string(input_string)
        output = ini.render()
        self.assertEqual(input_string, output)

    def test_pgb_ini_validate(self):
        pass
