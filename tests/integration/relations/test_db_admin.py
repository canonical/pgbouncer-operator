#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from tests.integration.helpers.helpers import (
    PG,
    PGB,
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

LANDSCAPE_APP_NAME = "landscape-server"
HAPROXY = "haproxy"
RABBITMQ = "rabbitmq-server"
RELATION = "db-admin"


@pytest.mark.unstable
@pytest.mark.abort_on_fail
async def test_db_admin_with_landscape(ops_test: OpsTest, pgb_charm_jammy) -> None:
    # Deploy application.
    await deploy_postgres_bundle(ops_test, pgb_charm_jammy, db_units=2, pgb_series="jammy")
    relation = await deploy_and_relate_application_with_pgbouncer_bundle(
        ops_test,
        LANDSCAPE_APP_NAME,
        LANDSCAPE_APP_NAME,
        series="jammy",
        relation=RELATION,
        force=True,
        wait=False,
    )
    await asyncio.gather(
        ops_test.model.deploy(
            HAPROXY,
            channel="stable",
            application_name=HAPROXY,
            num_units=1,
            series="focal",
        ),
        ops_test.model.deploy(
            RABBITMQ,
            channel="stable",
            application_name=RABBITMQ,
            num_units=1,
            series="focal",
        ),
    )
    await asyncio.gather(
        ops_test.model.relate(RABBITMQ, LANDSCAPE_APP_NAME),
        ops_test.model.relate(HAPROXY, LANDSCAPE_APP_NAME),
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[LANDSCAPE_APP_NAME, PG, PGB], status="active", timeout=1000
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

    landscape_users = [f"relation-{relation.id}"]

    await check_database_users_existence(ops_test, landscape_users, [])


@pytest.mark.unstable
async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:db-admin", f"{LANDSCAPE_APP_NAME}:db"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle([PG], status="active", timeout=300)
    for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(1), reraise=True):
        with attempt:
            assert len(ops_test.model.applications[PGB].units) == 0, "pgb units were not removed"
