# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
USERLIST_PATH = f"{PGB_DIR}/userlist.txt"
# TODO userlist path will be deleted when we switch over to the new relations
AUTH_FILE_PATH = f"{PGB_DIR}/userlist.txt"
LOG_PATH = f"{PGB_DIR}/pgbouncer.log"

# PGB config
DATABASES = "databases"

# legacy relation data
DB = "db"
DB_ADMIN = "db-admin"
BACKEND_DB_ADMIN = "backend-db-admin"
BACKEND_STANDBY_PREFIX = "pgb_postgres_standby_"
