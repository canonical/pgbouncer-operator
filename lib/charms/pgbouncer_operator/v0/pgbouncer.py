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

import secrets
import string
from typing import Dict

def generate_password() -> str:
    """Generates a secure password.

    Returns:
        A random 24-character string of letters and numbers.
    """
    choices = string.ascii_letters + string.digits
    return "".join([secrets.choice(choices) for _ in range(24)])

def generate_pgbouncer_ini(users: Dict[str, str], config) -> str:
    """Generate pgbouncer.ini from config.

    This is a basic stub method, and will be updated in future to generate more complex
    pgbouncer.ini files in a more sophisticated way.

    TODO compare to real-world pgbouncer.ini files and devise a more sophisticated way of
    generating them. Look at the previous charm's implementation of this.
    TODO evaluate other user types, such as stat_users etc
    TODO define/parse databases based on relation to postgres - does it need to be an exposed
    config option?

    Params:
        users: a dictionary of usernames and passwords
        config: charm config object.
    """

    return f"""[databases]
{config["pgb_databases"]}

[pgbouncer]
listen_port = {config["pgb_listen_port"]}
listen_addr = {config["pgb_listen_address"]}
auth_type = md5
auth_file = userlist.txt
logfile = pgbouncer.log
pidfile = pgbouncer.pid
admin_users = {",".join(users.keys())}"""


def generate_userlist(self, users: Dict[str, str]) -> str:
    """Generate userlist.txt from the given dictionary of usernames:passwords.

    Params:
        users: a dictionary of usernames and passwords
    Returns:
        A multiline string, containing each pair of usernames and passwords separated by a
        space, one pair per line.
    """
    return "\n".join([f'"{username}" "{password}"' for username, password in users.items()])