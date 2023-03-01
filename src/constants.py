# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_NAME = "pgbouncer.ini"
AUTH_FILE_NAME = "userlist.txt"

# PGB config
DATABASES = "databases"

# relation data
DB_RELATION_NAME = "db"
DB_ADMIN_RELATION_NAME = "db-admin"
BACKEND_RELATION_NAME = "backend-database"
PEERS = "pgb_peers"
PEER_RELATION_NAME = PEERS
CLIENT_RELATION_NAME = "database"
