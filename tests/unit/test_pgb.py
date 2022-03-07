# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import string
import unittest

import pytest

from lib.charms.dp_pgbouncer_operator.v0 import pgb


TEST_VALID_INI = "tests/unit/data/test.ini"

class TestPgb(unittest.TestCase):
    def test_generate_password(self):
        pw = pgb.generate_password()
        self.assertEqual(len(pw), 24)
        valid_chars = string.ascii_letters + string.digits
        for char in pw:
            assert char in valid_chars

    def test_generate_pgbouncer_ini(self):
        config = {
            "databases": {
                "test": {"host": "test", "port": "4039", "dbname": "testdatabase",},
                "test2": {"host": "test2"},
            },
            "pgbouncer": {
                "logfile": "test/logfile",
                "pidfile": "test/pidfile",
                "admin_users": ["Test"],
                "stats_users": ["Test", "test_stats"],
                "listen_port": "4545",
            },
            "users": {
                "Test": {
                    "pool_mode": "session",
                    "max_user_connections": "10",
                }
            },
        }

        generated_ini = pgb.generate_pgbouncer_ini(config)
        with open(TEST_VALID_INI, "r") as test_ini:
            expected_generated_ini = test_ini.read()
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
        with open(TEST_VALID_INI, "r") as test_ini:
            input_string = test_ini.read()
        ini = pgb.PgbIni()
        ini.parse_string(input_string)
        expected_dict = {"host": "test", "port": "4039", "dbname": "testdatabase"}
        self.assertDictEqual(ini["databases"]["test"], expected_dict)
        self.assertEqual(ini["pgbouncer"]["stats_users"], ["Test", "test_stats"])

    def test_pgb_ini_parse_dict(self):
        input_dict = {
            "databases": {
                "db1": {"dbname": "test"},
                "db2": {"host": "test_host"},
            },
            "pgbouncer": {
                "logfile": "/etc/pgbouncer/pgbouncer.log",
                "pidfile": "/etc/pgbouncer/pgbouncer.pid",
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
        with open(TEST_VALID_INI, "r") as test_ini:
            input_string = test_ini.read()
        ini = pgb.PgbIni()
        ini.parse_string(input_string)
        output = ini.render()
        self.assertEqual(input_string, output)

    def test_pgb_ini_validate(self):
        ini = pgb.PgbIni()
        with open(TEST_VALID_INI, "r") as test_ini:
            valid_ini = test_ini.read()
        ini.parse_string(valid_ini)

        # Recreate ini to ensure no carryover
        ini = pgb.PgbIni()
        with open("tests/unit/data/test_no_dbs.ini", "r") as test_ini_no_dbs:
            ini_no_dbs = test_ini_no_dbs.read()
        with pytest.raises(KeyError):
            ini.parse_string(ini_no_dbs)

        ini = pgb.PgbIni()
        with open("tests/unit/data/test_no_logfile.ini", "r") as test_ini_no_logfile:
            ini_no_logfile = test_ini_no_logfile.read()
        with pytest.raises(KeyError):
            ini.parse_string(ini_no_logfile)

        ini = pgb.PgbIni()
        with open("tests/unit/data/test_no_pidfile.ini", "r") as test_ini_no_pidfile:
            ini_no_pidfile = test_ini_no_pidfile.read()
        with pytest.raises(KeyError):
            ini.parse_string(ini_no_pidfile)

        ini = pgb.PgbIni()
        with open("tests/unit/data/test_bad_db.ini", "r") as test_ini_bad_db:
            ini_bad_db = test_ini_bad_db.read()
        with pytest.raises(pgb.PgbIni.IniParsingError):
            ini.parse_string(ini_bad_db)

        ini = pgb.PgbIni()
        with open("tests/unit/data/test_bad_dbname.ini", "r") as test_ini_bad_dbname:
            ini_bad_dbname = test_ini_bad_dbname.read()
        with pytest.raises(pgb.PgbIni.IniParsingError):
            ini.parse_string(ini_bad_dbname)
            ini.validate()

    def test_pgb_ini__validate_dbname(self):
        ini = pgb.PgbIni()
        good_dbnames = ["test-_1", 'test"%$"1', 'multiple"$"bad"^"values', '" "']
        for dbname in good_dbnames:
            ini._validate_dbname(dbname)

        bad_dbnames = ['"', "%", " ", '"$"test"']
        for dbname in bad_dbnames:
            with pytest.raises(pgb.PgbIni.IniParsingError):
                ini._validate_dbname(dbname)
