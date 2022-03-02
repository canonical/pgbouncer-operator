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
Kubernetes charms.
"""

import io
import logging
import secrets
import string
from configparser import ConfigParser
from typing import Dict

from ops.model import ConfigData

logger = logging.getLogger(__name__)

PGB_INI = """\
[databases]
{databases}
[pgbouncer]
listen_port = {listen_port}
listen_addr = {listen_addr}
auth_type = md5
auth_file = userlist.txt
logfile = pgbouncer.log
pidfile = pgbouncer.pid
admin_users = {admin_users}
"""


def generate_password() -> str:
    """Generates a secure password of alphanumeric characters.

    Passwords are alphanumeric only, to ensure compatibility with the userlist.txt format -
    specifically, spaces and double quotes may interfere with parsing this file.

    Returns:
        A random 24-character string of letters and numbers.
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for _ in range(24)])


def generate_pgbouncer_ini(users: Dict[str, str], config: ConfigData) -> str:
    """Generate pgbouncer.ini from config.

    This is a basic stub method, and will be updated in future to generate more complex
    pgbouncer.ini files in a more sophisticated way.

    Args:
        users: a dictionary of usernames and passwords
        config: A juju charm config object
    Returns:
        A multiline string defining a valid pgbouncer.ini file
    """
    return PGB_INI.format(
        databases=config["pgb_databases"],
        listen_port=config["pgb_listen_port"],
        listen_addr=config["pgb_listen_address"],
        admin_users=",".join(users.keys()),
    )


def generate_pgbouncer_ini_better(dbconfig: Dict[str, Dict[str, str]], **kwargs) -> str:
    """Generate pgbouncer.ini using IniParser object.
    Args:
        dbconfig: database config dictionary
        kwargs: kwargs following the [pgbouncer config spec](https://pgbouncer.org/config.html).
            Note that admin_users and stats_users must be passed in as lists of strings, not in
            their string representation in the .ini file.
    """
    import logging

    logging.info(type(kwargs))
    parser = IniParser()
    cfg_dict = {"databases": dbconfig, "pgbouncer": kwargs}
    parser.read_dict(cfg_dict)
    return parser.write_to_string()


def generate_userlist(users: Dict[str, str]) -> str:
    """Generate userlist.txt from the given dictionary of usernames:passwords.

    Args:
        users: a dictionary of usernames and passwords
    Returns:
        A multiline string, containing each pair of usernames and passwords separated by a
        space, one pair per line.
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


class IniParser(ConfigParser):
    """A ConfigParser class used to read, write, and edit pgbouncer.ini config files.

    This class also includes some variables for accessing more complex config entries
    programmatically; where the .ini file stores them as delimited strings, this object stores
    them as dictionaries"""

    db_section = "databases"
    pgb_section = "pgbouncer"
    user_types = ["admin_users", "stats_users"]

    def __init__(self, *args):
        super().__init__(*args)
        # Preserve case in string values
        self.optionxform = str

        self.dbs = {}
        self.users = {}

    def _read(self, fp, fpname) -> None:
        """Reads a pgbouncer.ini file, and uses it to populate this object.

        Overrides ConfigParser._read() method to include pgbouncer-specific parsing of nested
        values. This method therefore also removes comments from the .ini file.

        The existing ConfigParser._read() method adequately parses the config, but it's useful for
        us to parse dictionary and list values (such as databases and admin_users, respectively)
        explicitly, so we can access and modify those values as we need. This necessitates
        modifying the parent method's write() function to correctly encode these lists. This method
        is private, since the parent class' read methods should be used.

        Args:
            fp: filepath to be read. Must be iterable.
            fpname: Source of filepath - for example, <String>
        """
        super()._read(fp, fpname)
        self._parse_complex_values()

    def _parse_complex_values(self) -> None:
        """Copies complex config values from strings into more suitable python representations."""
        # Parse nested dbs from space-separated key=value pairs to a dict.
        for name, db_config in self[IniParser.db_section].items():
            db_config_dict = {}
            for kv_pair in db_config.split(" "):
                key, value = kv_pair.split("=")
                db_config_dict[key] = value
            self.dbs[name] = db_config_dict

        # Parse user lists from comma-separated strings to python lists.
        for user in IniParser.user_types:
            try:
                userlist = self[IniParser.pgb_section][user]
                self.users[user] = userlist.split(",")
            except KeyError:
                # If a user type doesn't exist, that's not a problem.
                pass

    def _encode_complex_values(self) -> None:
        """Writes config values from accessible local variables to pgb-readable strings."""
        # Encode db dicts to writable strings
        for name, dbconfig in self.dbs.items():
            # Split each dbconfig value into a space-separated string of key-value pairs
            self[IniParser.db_section][name] = " ".join(
                [f"{key}={value}" for key, value in dbconfig.items()]
            )

        # Encode user lists back to writable strings
        for userlist in IniParser.user_types:
            try:
                self[IniParser.pgb_section][userlist] = ",".join(self.users[userlist])
            except KeyError:
                # If a user type doesn't exist, that's not a problem.
                pass

    def read_dict(self, dictionary, source="<dict>") -> None:
        """Reads a dictionary and uses it to populate this object.

        Overrides ConfigParser.read_dict() parent method, including some parsing for unique
        pgbouncer variables.

        Args:
            dictionary: the dictionary to be read into this object. When forming this dictionary,
                ensure database config is written as a sub-dictionary, and user config is written
                as a list, rather than using the pgbouncer config string representation.
            source: the source of the dict (used primarily for logging)
        """
        super().read_dict(dictionary, source)
        self.dbs = dict(dictionary["databases"])
        for user_type in IniParser.user_types:
            try:
                if isinstance(dictionary["pgbouncer"][user_type], str):
                    self.users[user_type] = [dictionary["pgbouncer"][user_type]]
                else:
                    self.users[user_type] = list(dictionary["pgbouncer"][user_type])
            except KeyError:
                # If a user_type doesn't exist, that's not a problem.
                pass
        self._encode_complex_values()

    def write(self, fp, space_around_delimiter=True):
        """Write a pgbouncer file to the given filepath.

        Overrides ConfigParser.write() method to include pgb-specific parsing of nested values.

        The existing ConfigParser.write() method adequately encodes simple config values, but
        certain values are parsed into python lists/dicts in Ini._read(), for utility. These values
        have to be re-encoded back to their string representations before they are written to a
        file.

        Args:
            fp: Iterable filepath object for
            space_around_delimiter: whether or not to have spaces around delimiter
        """

        # Use ConfigParser.write() to write the file normally.
        super().write(fp, space_around_delimiter)
        self._encode_complex_values()

    def write_to_string(self) -> str:
        """Writes class to a string, capable of being written to a pgbouncer.ini config file.

        Returns:
            str: a string that can be sent to a pgbouncer.ini file.
        """
        with io.StringIO() as string_io:
            self.write(string_io)
            string_io.seek(0)
            rtn_string = string_io.read()
        return rtn_string
