#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from .helpers.helpers import (
    PG,
    PGB,
)
from .helpers.postgresql_helpers import get_leader_unit
from .relations.pgbouncer_provider.helpers import (
    check_exposed_connection,
    fetch_action_get_credentials,
)

logger = logging.getLogger(__name__)

TIMEOUT = 600
DATA_INTEGRATOR_APP_NAME = "data-integrator"


@pytest.mark.abort_on_fail
async def test_deploy_stable(ops_test: OpsTest, charm) -> None:
    """Simple test to ensure that the PostgreSQL and application charms get deployed."""
    await asyncio.gather(
        ops_test.model.deploy(
            PG,
            num_units=3,
            channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
            config={"profile": "testing"},
        ),
        ops_test.model.deploy(
            PGB,
            channel="1/stable",
            num_units=0,
        ),
        ops_test.model.deploy(
            DATA_INTEGRATOR_APP_NAME,
            num_units=2,
            channel="latest/edge",
            config={"database-name": "test-database"},
            series="jammy",
        ),
    )
    logger.info("Wait for applications to become active")

    await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.add_relation(DATA_INTEGRATOR_APP_NAME, PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[PG, PGB, DATA_INTEGRATOR_APP_NAME], status="active", timeout=1500
        )
    assert len(ops_test.model.applications[PG].units) == 3
    assert len(ops_test.model.applications[PGB].units) == 2


@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, PGB)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()


@pytest.mark.abort_on_fail
async def test_upgrade_from_stable(ops_test: OpsTest, charm):
    """Test updating from stable channel."""
    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)

    application = ops_test.model.applications[PGB]
    actions = await application.get_actions()

    logger.info("Refresh the charm")
    await application.refresh(path=charm)

    logger.info("Wait for upgrade to start")
    await ops_test.model.block_until(
        lambda: ("waiting" if "pre-upgrade-check" in actions else "maintenance")
        in {unit.workload_status for unit in application.units},
        timeout=TIMEOUT,
    )

    logger.info("Wait for upgrade to complete")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[PGB], status="active", idle_period=30, timeout=TIMEOUT
        )

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)
