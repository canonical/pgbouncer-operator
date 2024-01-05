#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from tests.integration.helpers.helpers import (
    PG,
    PGB,
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_app_relation_databag,
    run_sql,
)

logger = logging.getLogger(__name__)

PSQL = "psql"
RELATION = "db-admin"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_db_admin_with_psql(ops_test: OpsTest, pgb_charm_focal) -> None:
    await deploy_postgres_bundle(
        ops_test,
        pgb_charm_focal,
        db_units=2,
        pgb_series="focal",
    )

    psql_relation = await deploy_and_relate_application_with_pgbouncer_bundle(
        ops_test,
        "postgresql-charmers-postgresql-client",
        PSQL,
        relation=RELATION,
        series="focal",
    )

    unit_name = f"{PSQL}/0"
    psql_databag = await get_app_relation_databag(ops_test, unit_name, psql_relation.id)

    pgpass = psql_databag.get("password")
    user = psql_databag.get("user")
    host = psql_databag.get("host")
    port = psql_databag.get("port")
    dbname = psql_databag.get("database")

    assert None not in [pgpass, user, host, port, dbname], "databag incorrectly populated"

    user_command = "CREATE ROLE myuser3 LOGIN PASSWORD 'mypass';"
    rtn, _, err = await run_sql(
        ops_test, unit_name, user_command, pgpass, user, host, port, dbname
    )
    assert rtn == 0, f"failed to run admin command {user_command}, {err}"

    db_command = "CREATE DATABASE test_db;"
    rtn, _, err = await run_sql(ops_test, unit_name, db_command, pgpass, user, host, port, dbname)
    assert rtn == 0, f"failed to run admin command {db_command}, {err}"


@pytest.mark.group(1)
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[PGB].remove_relation(f"{PGB}:db-admin", f"{PSQL}:db")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle([PG], status="active", timeout=300)
    for attempt in Retrying(stop=stop_after_attempt(60), wait=wait_fixed(1), reraise=True):
        with attempt:
            assert len(ops_test.model.applications[PGB].units) == 0, "pgb units were not removed"
