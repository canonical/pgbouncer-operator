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
    deploy_and_relate_bundle_with_pgbouncer,
    deploy_postgres_bundle,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

LANDSCAPE_APP_NAME = "landscape-server"
LANDSCAPE_SCALABLE_BUNDLE_NAME = "ch:landscape-scalable"
RELATION = "db-admin"


@pytest.mark.abort_on_fail
async def test_db_admin_with_psql(ops_test: OpsTest, pgb_charm) -> None:
    # Deploy application.
    await deploy_postgres_bundle(ops_test, pgb_charm, db_units=2, pgb_series="jammy")
    relation_id = await deploy_and_relate_bundle_with_pgbouncer(
        ops_test,
        LANDSCAPE_SCALABLE_BUNDLE_NAME,
        LANDSCAPE_APP_NAME,
    )

    await check_databases_creation(
        ops_test,
        [
            "landscape-account-1",
            "landscape-knowledge",
            "landscape-main",
            "landscape-package",
            "landscape-resource-1",
            "landscape-session",
        ],
    )

    landscape_users = [f"relation-{relation_id}"]

    await check_database_users_existence(ops_test, landscape_users, [])


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:db-admin", f"{LANDSCAPE_APP_NAME}:db"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle([PG], status="active", timeout=300)
    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True):
        with attempt:
            assert len(ops_test.model.applications[PGB].units) == 0, "pgb units were not removed"
