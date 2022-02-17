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

"""
This charm library provides common pgbouncer-specific features for the pgbouncer machine and
Kubernetes charms.
"""

import secrets
import string
from typing import Dict

from ops.model import ConfigData

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
    Returns:
        A multiline string defining a valid pgbouncer.ini file
    """
    return PGB_INI.format(
        databases=config["pgb_databases"],
        listen_port=config["pgb_listen_port"],
        listen_addr=config["pgb_listen_address"],
        admin_users=",".join(users.keys()),
    )


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
        if line.strip() == "" or len(line.split(" ")) != 2:
            continue
        # Userlist is formatted "{username}" "{password}""
        username, password = line.replace('"', "").split(" ")
        parsed_userlist[username] = password

    return parsed_userlist
