# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers.helpers import (
    scale_application,
    wait_for_relation_joined_between,
    wait_for_relation_removed_between,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"
BACKEND_RELATION = "backend-database"
MAILMAN = "mailman3-core"


@pytest.mark.scaling
@pytest.mark.abort_on_fail
@pytest.mark.run(order=1)
# TODO order marks aren't behaving
async def test_deploy_at_scale(ops_test):
    # Build, deploy, and relate charms.
    charm = await ops_test.build_charm(".")
    async with ops_test.fast_forward():
        await ops_test.model.deploy(charm, application_name=PGB, num_units=3)
        await ops_test.model.wait_for_idle(
            apps=[PGB], status="blocked", timeout=600, wait_for_exact_units=3
        ),


@pytest.mark.scaling
@pytest.mark.abort_on_fail
@pytest.mark.run(order=2)
async def test_scaled_relations(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(PG, channel="edge", trust=True, num_units=3),
            ops_test.model.deploy(MAILMAN, application_name=MAILMAN, channel="edge"),
        )

        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[PGB], status="blocked", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION}", f"{PG}:database")
        wait_for_relation_joined_between(ops_test, PG, PGB)

        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        await ops_test.model.add_relation(f"{PGB}:db", f"{MAILMAN}:db")
        wait_for_relation_joined_between(ops_test, PGB, MAILMAN)
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[MAILMAN], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )


@pytest.mark.scaling
@pytest.mark.run(order=3)
async def test_scaling(ops_test: OpsTest):
    """Test data is replicated to new units after a scale up."""
    # Ensure the initial number of units in the application.
    initial_scale = 4
    async with ops_test.fast_forward():
        await scale_application(ops_test, PGB, initial_scale)
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[MAILMAN], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=initial_scale
            ),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        # Scale down the application.
        await scale_application(ops_test, PGB, initial_scale - 1)
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[MAILMAN], status="active", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PGB], status="active", timeout=600, wait_for_exact_units=initial_scale - 1
            ),
        )


@pytest.mark.scaling
@pytest.mark.run(order=4)
async def test_exit_relations(ops_test: OpsTest):
    """Test that we can exit relations with multiple units without breaking anything."""
    async with ops_test.fast_forward():
        await ops_test.model.remove_application(MAILMAN)
        wait_for_relation_removed_between(ops_test, PGB, MAILMAN)
        await ops_test.model.wait_for_idle(apps=[PG, PGB], status="active", timeout=600)

        await ops_test.model.remove_application(PG)
        wait_for_relation_removed_between(ops_test, PG, PGB)
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)
