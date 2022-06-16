# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import psycopg2
import asyncio
import logging
from pathlib import Path

from charms.pgbouncer_operator.v0 import pgb

import yaml
from pytest_operator.plugin import OpsTest

from tests.integration import helpers

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.abort_on_fail
# TODO assert ordering of integration tests, specifically in deployment. Maybe relation tests
# should be a separate thing entirely?
async def test_create_backend_db_admin_relation_slowtest_current(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another.

    This test is marked "slowtest", meaning it won't run when you run "tox -e fast-integration".
    This is because it's very slow.
    """
    # Build, deploy, and relate charms.
    pg = "postgresql"
    charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            charm,
            application_name=APP_NAME,
        ),
        ops_test.model.deploy(pg),
    )
    # Pgbouncer enters a waiting state without backend postgres relation
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="waiting", timeout=1000)
    await ops_test.model.add_relation(f"{APP_NAME}:backend-db-admin", f"{pg}:db-admin")
    # Pgbouncer enters a waiting status without a postgres backend database relation
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)

    unit = ops_test.model.units["pgbouncer-operator/0"]
    cfg = await helpers.get_cfg(unit)
    # When there's only one postgres unit, we're in "standalone" mode with no standby replicas.
    assert list(cfg["databases"].keys()) == ["pg_master"]

    #Test pgbouncer database exists on postgres charm
    host = await helpers.get_unit_address(ops_test, pg, f"{APP_NAME}/0")
    logger.info("connecting to the database host: %s", host)
    password = pgb.parse_kv_string_to_dict(cfg["databases"]["pg_master"])["password"]
    with psycopg2.connect(
        #TODO could replace most of this string (apart from connect_timeout) with cfg pg_master val.
        f"dbname='pgbouncer-operator' user='jujuadmin_pgbouncer-operator' host='{host}' password='{password}' connect_timeout=1"
    ) as connection, connection.cursor() as cursor:
        assert connection.status == psycopg2.extensions.STATUS_READY

        # Retrieve settings from PostgreSQL pg_settings table.
        # Here the SQL query gets a key-value pair composed by the name of the setting
        # and its value, filtering the retrieved data to return only the settings
        # that were set by Patroni.
        cursor.execute(
            """SELECT datname FROM pg_catalog.pg_database WHERE datname='pgbouncer-operator'"""
        )
        records = cursor.fetchall()
        assert "pgbouncer-operator" in records


async def test_backend_db_admin_relation_scaling_slowtest_current(ops_test: OpsTest):
    """Test that the pgbouncer config accurately reflects postgres replication changes.

    Requires existing deployed pgbouncer and legacy postgres charms, connected by a
    backend-db-admin relation
    """
    pg = "postgresql"
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.applications[pg].add_units(count=2)
    await asyncio.gather(
        ops_test.model.wait_for_idle(
            apps=[pg], status="active", timeout=1000, wait_for_exact_units=3
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
        ),
    )
    cfg = await helpers.get_cfg(unit)
    # Now there are three postgres units, we're in "standby" mode, with two standby replicas.
    assert list(cfg["databases"].keys()) == [
        "pg_master",
        "pgb_postgres_standby_0",
        "pgb_postgres_standby_1",
    ]

    await ops_test.model.destroy_unit("postgresql/2")
    await asyncio.gather(
        ops_test.model.wait_for_idle(
            apps=[pg], status="active", timeout=1000, wait_for_exact_units=2
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
        ),
    )
    cfg = await helpers.get_cfg(unit)
    # Now there are two postgres units, and the config reflects this.
    assert list(cfg["databases"].keys()) == ["pg_master", "pgb_postgres_standby_0"]
    assert "pgb_postgres_standby_1" not in cfg["databases"].keys()

    await ops_test.model.destroy_unit("postgresql/1")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)
    cfg = await helpers.get_cfg(unit)
    # Now there is only one config, with no replicas, and the config reflects this.
    assert list(cfg["databases"].keys()) == ["pg_master"]
    assert "pgb_postgres_standby_0" not in cfg["databases"].keys()

    # Remove relation but keep pg application because we're going to need it for future tests.
    await ops_test.model.remove_relation(f"{APP_NAME}:backend-db-admin", f"{pg}:db-admin")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)
    cfg = await helpers.get_cfg(unit)
    # assert pgb and pg are completely disconnected.
    assert "pg_master" not in cfg["databases"].keys()
