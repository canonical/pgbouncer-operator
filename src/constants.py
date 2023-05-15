# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PG_USER = "snap_daemon"
PGB_DIR = "/var/snap/charmed-postgresql/common/var/lib/pgbouncer"
INI_NAME = "pgbouncer.ini"
AUTH_FILE_NAME = "userlist.txt"

# Snap constants.
PGBOUNCER_EXECUTABLE = "charmed-postgresql.pgbouncer"
POSTGRESQL_SNAP_NAME = "charmed-postgresql"
SNAP_PACKAGES = [(POSTGRESQL_SNAP_NAME, {"revision": 43})]

# PGB config
DATABASES = "databases"

# relation data
DB_RELATION_NAME = "db"
DB_ADMIN_RELATION_NAME = "db-admin"
BACKEND_RELATION_NAME = "backend-database"
PEER_RELATION_NAME = "pgb-peers"
CLIENT_RELATION_NAME = "database"
