# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"
USERLIST_PATH = f"{PGB_DIR}/userlist.txt"

# PGB config
DATABASES = "databases"

# legacy relation data
DB = "db"
DB_ADMIN = "db-admin"
BACKEND_DB_ADMIN = "backend-db-admin"
BACKEND_STANDBY_PREFIX = "pgb_postgres_standby_"
