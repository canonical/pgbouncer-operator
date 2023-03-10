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
    WEEBL,
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
)
from tests.integration.helpers.postgresql_helpers import check_databases_creation

logger = logging.getLogger(__name__)

APPLICATION_UNITS = 1
DATABASE_UNITS = 2
RELATION_NAME = "db"


@pytest.mark.abort_on_fail
async def test_weebl_db(ops_test: OpsTest, pgb_charm) -> None:
    """Deploy Weebl to test the 'db' relation."""
    backend_relation = await deploy_postgres_bundle(
        ops_test,
        pgb_charm,
        db_units=DATABASE_UNITS,
        pgb_series="jammy",
    )

    # Deploy and test the deployment of Weebl.
    await deploy_and_relate_application_with_pgbouncer_bundle(
        ops_test,
        WEEBL,
        WEEBL,
        series="jammy",
        force=True,
    )

    pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)
    await check_databases_creation(ops_test, ["bugs_database"], pgb_user, pgb_pass)


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[PGB].remove_relation(f"{PGB}:db", f"{WEEBL}:database")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle([PG], status="active", timeout=300)
    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True):
        with attempt:
            assert len(ops_test.model.applications[PGB].units) == 0, "pgb units were not removed"
