# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from constants import PG
from tests.integration import helpers

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PSQL = "psql"
APPS = [PG, PGB, PSQL]


@pytest.mark.abort_on_fail
@pytest.mark.legacy_relations
async def test_create_db_legacy_relation(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            charm,
            application_name=PGB,
        ),
        ops_test.model.deploy(PG),
        ops_test.model.deploy("postgresql-charmers-postgresql-client", application_name="psql"),
    )

    # Pgbouncer enters a blocked state without backend postgres relation
    await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=1000)
    await ops_test.model.add_relation(f"{PGB}:db", f"{PSQL}:db")
    await ops_test.model.add_relation(f"{PGB}:backend-db-admin", f"{PG}:db-admin")
    await ops_test.model.wait_for_idle(apps=APPS, status="active", timeout=1000)

    unit = ops_test.model.units["pgbouncer-operator/0"]
    cfg = await helpers.get_cfg(unit)
    assert "pg_master" in list(cfg["databases"].keys())
    logging.error(list(cfg["databases"].keys()))

    # Test pgbouncer database exists on postgres charm
    # This section currently doesn't work, because postgresql has security rules that block access
    # from anywhere that isn't the pgbouncer charm. This is great, except that I can't access
    # anything for testing.

    # TODO test with the following command:
    # psql --host=10.101.233.51 --port=6432 --username=jujuadmin_pgbouncer-operator \
    # --password --dbname=pgbouncer-operator

    # connection_string = pgb.parse_dict_to_kv_string(cfg['databases']['pg_master'])
    # with psycopg2.connect(
    #     f"{connection_string} connect_timeout=1"
    # ) as connection, connection.cursor() as cursor:
    #     assert connection.status == psycopg2.extensions.STATUS_READY

    #     # Retrieve settings from PostgreSQL pg_settings table.
    #     # Here the SQL query gets a key-value pair composed by the name of the setting
    #     # and its value, filtering the retrieved data to return only the settings
    #     # that were set by Patroni.
    #     cursor.execute(
    #         """SELECT datname
    #         FROM pg_catalog.pg_database
    #         WHERE datname='pgbouncer-operator'"""
    #     )
    #     records = cursor.fetchall()
    #     assert "pgbouncer-operator" in records

async def test_remove_db_legacy_relation(ops_test: OpsTest):
    """Test that removing relations still works ok"""
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:db", f"{PSQL}:db"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, PG], status="active", timeout=1000)
    unit = ops_test.model.units["pgbouncer-operator/0"]
    cfg = await helpers.get_cfg(unit)
    # assert pgbouncer and postgres are completely disconnected.
    assert "pg_master" not in cfg["databases"].keys()