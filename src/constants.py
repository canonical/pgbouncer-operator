# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Literals for the PgBouncer charm."""

PGB = "pgbouncer"
PG = "postgres"
PG_USER = "snap_daemon"
INI_NAME = "pgbouncer.ini"
AUTH_FILE_NAME = "userlist.txt"

# Snap constants.
PGBOUNCER_SNAP_NAME = "charmed-pgbouncer"
PGBOUNCER_EXECUTABLE = f"{PGBOUNCER_SNAP_NAME}.pgbouncer"
SNAP_PACKAGES = [
    (
        PGBOUNCER_SNAP_NAME,
        {"revision": {"aarch64": "5", "x86_64": "6"}, "channel": "1/stable"},
    )
]

SNAP_COMMON_PATH = f"/var/snap/{PGBOUNCER_SNAP_NAME}/common"
SNAP_CURRENT_PATH = f"/var/snap/{PGBOUNCER_SNAP_NAME}/current"

PGB_CONF_DIR = f"{SNAP_CURRENT_PATH}/etc/pgbouncer"
PGB_LOG_DIR = f"{SNAP_COMMON_PATH}/var/log/pgbouncer"

SNAP_TMP_DIR = f"/tmp/snap-private-tmp/snap.{PGBOUNCER_SNAP_NAME}/tmp"

# PGB config
DATABASES = "databases"

# relation data
DB_RELATION_NAME = "db"
DB_ADMIN_RELATION_NAME = "db-admin"
BACKEND_RELATION_NAME = "backend-database"
PEER_RELATION_NAME = "pgb-peers"
CLIENT_RELATION_NAME = "database"
HACLUSTER_RELATION_NAME = "ha"

TLS_KEY_FILE = "key.pem"
TLS_CA_FILE = "ca.pem"
TLS_CERT_FILE = "cert.pem"

MONITORING_PASSWORD_KEY = "monitoring_password"
CFG_FILE_DATABAG_KEY = "cfg_file"
AUTH_FILE_DATABAG_KEY = "auth_file"

EXTENSIONS_BLOCKING_MESSAGE = "bad relation request - remote app requested extensions, which are unsupported. Please remove this relation."

SECRET_LABEL = "secret"
SECRET_INTERNAL_LABEL = "internal-secret"
SECRET_DELETED_LABEL = "None"

APP_SCOPE = "app"
UNIT_SCOPE = "unit"

SECRET_KEY_OVERRIDES = {
    "cfg_file": "cfg-file",
    "monitoring_password": "monitoring-password",
    "auth_file": "auth-file",
    "ca": "cauth",
}

SOCKET_LOCATION = f"/tmp/snap-private-tmp/snap.{PGBOUNCER_SNAP_NAME}/tmp/pgbouncer/instance_0"

TRACING_RELATION_NAME = "tracing"
TRACING_PROTOCOL = "otlp_http"
