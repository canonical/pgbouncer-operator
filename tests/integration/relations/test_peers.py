# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME
from tests.integration.helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
    WAIT_MSG,
    scale_application,
    wait_for_relation_joined_between,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_deploy_at_scale(ops_test, application_charm, pgb_charm):
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                application_charm, application_name=CLIENT_APP_NAME, num_units=3
            ),
            ops_test.model.deploy(
                pgb_charm,
                application_name=PGB,
                num_units=None,
            ),
        )
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
        # Pgbouncer enters a blocked status without a postgres backend database relation
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)
    assert ops_test.model.units[f"{PGB}/0"].workload_status_message == WAIT_MSG


@pytest.mark.abort_on_fail
async def test_scaled_relations(ops_test: OpsTest):
    """Test that the pgbouncer, postgres, and client charms can relate to one another."""
    # Build, deploy, and relate charms.
    async with ops_test.fast_forward():
        await ops_test.model.deploy(PG, channel="edge", trust=True, num_units=3),

        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[PGB], status="blocked", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=1000, wait_for_exact_units=3
            ),
        )

        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        wait_for_relation_joined_between(ops_test, PG, PGB)

        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )


async def test_scaling(ops_test: OpsTest):
    """Test data is replicated to new units after a scale up."""
    # Ensure the initial number of units in the application.
    initial_scale = 4
    async with ops_test.fast_forward():
        await scale_application(ops_test, CLIENT_APP_NAME, initial_scale)
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=initial_scale
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        # Scale down the application.
        await scale_application(ops_test, CLIENT_APP_NAME, initial_scale - 1)
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=initial_scale - 1
            ),
        )


async def test_exit_relations(ops_test: OpsTest):
    """Test that we can exit relations with multiple units without breaking anything."""
    async with ops_test.fast_forward():
        await ops_test.model.remove_application(PG, block_until_done=True)
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)

        await ops_test.model.remove_application(CLIENT_APP_NAME, block_until_done=True)
