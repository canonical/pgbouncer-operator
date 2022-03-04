# Copyright 2022 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PgBouncer Charm Library.

This charm library provides common pgbouncer-specific features for the pgbouncer machine and
Kubernetes charms, including automatic config management.
"""

import io
import logging
import secrets
import string
from collections.abc import MutableMapping
from configparser import ConfigParser
from typing import Dict, List

logger = logging.getLogger(__name__)


def generate_password() -> str:
    """Generates a secure password of alphanumeric characters.

    Passwords are alphanumeric only, to ensure compatibility with the userlist.txt format -
    specifically, spaces and double quotes may interfere with parsing this file.

    Returns:
        A random 24-character string of letters and numbers.
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for _ in range(24)])


def generate_pgbouncer_ini(**kwargs) -> str:
    """Generate pgbouncer.ini file from the given config options.

    Args:
        kwargs: kwargs following the [pgbouncer config spec](https://pgbouncer.org/config.html).
            Note that admin_users and stats_users must be passed in as lists of strings, not in
            their string representation in the .ini file.
    """
    ini = PgbIni()
    ini.parse_dict(kwargs)
    return ini.render()


def generate_userlist(users: Dict[str, str]) -> str:
    """Generate valid userlist.txt from the given dictionary of usernames:passwords.

    Args:
        users: a dictionary of usernames and passwords
    Returns:
        A multiline string, containing each pair of usernames and passwords in double quotes,
        separated by a space, one pair per line.
    """
    return "\n".join([f'"{username}" "{password}"' for username, password in users.items()])


def parse_userlist(userlist: str) -> Dict[str, str]:
    """Parse userlist.txt into a dictionary of usernames and passwords.

    Args:
        userlist: a multiline string of users and passwords, formatted thusly:
        '''
        "test-user" "password"
        "juju-admin" "asdf1234"
        '''
    Returns:
        users: a dictionary of usernames and passwords
    """
    parsed_userlist = {}
    for line in userlist.split("\n"):
        if (
            line.strip() == ""
            or len(line.split(" ")) != 2
            or len(line.replace('"', "")) != len(line) - 4
        ):
            logger.warning("unable to parse line in userlist file - user not imported")
            continue
        # Userlist is formatted "{username}" "{password}""
        username, password = line.replace('"', "").split(" ")
        parsed_userlist[username] = password

    return parsed_userlist


class PgbIni(MutableMapping):
    """A mapping that represents the pgbouncer config."""

    # Define names of ini sections:
    # [databases] defines the config options for each database. This section is mandatory.
    # [pgbouncer] defines pgbouncer-specific config
    # [users] defines config for specific users.
    db_section = "databases"
    pgb_section = "pgbouncer"
    users_section = "users"
    pgb_list_entries = ["admin_users", "stats_users"]

    def __init__(self, *args, **kwargs):
        self.__dict__.update(*args, **kwargs)

    def __delitem__(self, key):
        """Deletes item from internal mapping."""
        del self.__dict__[key]

    def __getitem__(self, key):
        """Gets item from internal mapping."""
        return self.__dict__[key]

    def __setitem__(self, key, value):
        """Set an item in internal mapping."""
        self.__dict__[key] = value

    def __iter__(self):
        """Returns an iterable of internal mapping."""
        return iter(self.__dict__)

    def __len__(self):
        """Gets number of key-value pairs in internal mapping."""
        return len(self.__dict__)

    def parse_string(self, input: str) -> None:
        """Populates this class from a pgbouncer.ini file, passed in as a string.

        Args:
            input: pgbouncer.ini file to be parsed, represented as a string
        """
        # Since the parser persists data across reads, we have to create a new one for every read.
        parser = ConfigParser()
        parser.optionxform = str
        parser.read_string(input)

        self.__dict__.update(dict(parser).copy())
        for section, data in self.__dict__.items():
            self.__dict__[section] = dict(data)
        del self["DEFAULT"]

        self._parse_complex_variables()
        self.validate()

    def _parse_complex_variables(self) -> None:
        """Parse complex config variables from string representation into dicts."""
        db = PgbIni.db_section
        users = PgbIni.users_section
        pgb = PgbIni.pgb_section

        # No error checking for [databases] section, since it has to exist for pgbouncer to run.
        for name, cfg_string in self[db].items():
            self[db][name] = self._parse_string_to_dict(cfg_string)

        try:
            for name, cfg_string in self[users].items():
                self[users][name] = self._parse_string_to_dict(cfg_string)
        except KeyError:
            # [users] section is not compulsory, so continue.
            pass

        for pgb_lst in PgbIni.pgb_list_entries:
            try:
                self[pgb][pgb_lst] = self._parse_string_to_list(self[pgb][pgb_lst])
            except KeyError:
                # stats_users doesn't have to exist
                pass

    def _parse_string_to_dict(self, string: str) -> Dict[str, str]:
        """Parses space-separated key=value pairs into a python dict."""
        parsed_dict = {}
        for kv_pair in string.split(" "):
            key, value = kv_pair.split("=")
            parsed_dict[key] = value
        return parsed_dict

    def _parse_dict_to_string(self, dictionary: Dict[str, str]) -> str:
        """Helper function to encode a python dict into a pgbouncer-readable string."""
        return " ".join([f"{key}={value}" for key, value in dictionary.items()])

    def _parse_string_to_list(self, string: str) -> List[str]:
        """Parses comma-separated strings to a list."""
        return string.split(",")

    def _parse_list_to_string(self, ls: List[str]) -> str:
        """Helper function to encode a list into a comma-separated string."""
        return ",".join(ls)

    def parse_dict(self, input: Dict) -> None:
        """Populates this object from a dictionary.

        Args:
            input: Dict to be parsed into this object. This dict must follow the pgbouncer config
            spec (https://pgbouncer.org/config.html) to pass validation, implementing each section
            as its own subdict. Lists should be represented as python lists, not comma-separated
            strings.
        """
        self.__dict__.update(input)
        self.validate()

    def render(self) -> str:
        """Returns a valid pgbouncer.ini file as a string.

        Returns:
            str: a string that can be sent to a pgbouncer.ini file.
        """
        self.validate()

        # Populate parser object with local data.
        parser = ConfigParser()
        parser.optionxform = str

        output_dict = dict(self).copy()
        for section, subdict in output_dict.items():
            for option, config in subdict.items():
                if isinstance(config, dict):
                    output_dict[section][option] = self._parse_dict_to_string(config)
                elif isinstance(config, list):
                    output_dict[section][option] = self._parse_list_to_string(config)

        parser.read_dict(output_dict)

        # ConfigParser can only write to a file, so create a StringIO object to fool it.
        with io.StringIO() as string_io:
            parser.write(string_io)
            string_io.seek(0)
            output = string_io.read()
        return output

    def validate(self):
        """Validates that this will provide a valid pgbouncer.ini config when rendered."""
        if not self[PgbIni.db_section]:
            raise KeyError("database config not available")
