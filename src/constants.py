# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
AUTH_FILE_PATH = f"{PGB_DIR}/userlist.txt"
LOG_PATH = f"{PGB_DIR}/pgbouncer.log"

# PGB config
DATABASES = "databases"

# relation data
DB_RELATION_NAME = "db"
DB_ADMIN_RELATION_NAME = "db-admin"
BACKEND_DATABASE_RELATION_NAME = "backend-database"
PEERS = "pgb-peers"
