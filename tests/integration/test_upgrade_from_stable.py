#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from .helpers.ha_helpers import (
    are_writes_increasing,
    check_writes,
    start_continuous_writes,
)
from .helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
)
from .helpers.postgresql_helpers import get_leader_unit

logger = logging.getLogger(__name__)

TIMEOUT = 600


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_stable(ops_test: OpsTest, pgb_charm_jammy) -> None:
    """Simple test to ensure that the PostgreSQL and application charms get deployed."""
    await asyncio.gather(
        ops_test.model.deploy(
            PG,
            num_units=3,
            channel="14/edge",
            config={"profile": "testing"},
        ),
        # TODO use stable when it works with 3.1.7
        ops_test.model.deploy(
            PGB,
            channel="1/candidate",
            num_units=None,
        ),
        ops_test.model.deploy(
            CLIENT_APP_NAME,
            num_units=3,
            channel="latest/edge",
        ),
    )
    logger.info("Wait for applications to become active")

    await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[PG, PGB, CLIENT_APP_NAME], status="active", timeout=1500
        )
    assert len(ops_test.model.applications[PG].units) == 3
    assert len(ops_test.model.applications[PGB].units) == 3


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, PGB)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_upgrade_from_stable(ops_test: OpsTest, pgb_charm_jammy):
    """Test updating from stable channel."""
    # Start an application that continuously writes data to the database.
    logger.info("starting continuous writes to the database")
    await start_continuous_writes(ops_test, PGB)

    # Check whether writes are increasing.
    logger.info("checking whether writes are increasing")
    await are_writes_increasing(ops_test)

    application = ops_test.model.applications[PGB]
    actions = await application.get_actions()

    logger.info("Refresh the charm")
    await application.refresh(path=pgb_charm_jammy)

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

    # Check whether writes are increasing.
    logger.info("checking whether writes are increasing")
    await are_writes_increasing(ops_test)

    # Verify that no writes to the database were missed after stopping the writes
    # (check that all the units have all the writes).
    logger.info("checking whether no writes were lost")
    await check_writes(ops_test)
