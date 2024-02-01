#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME
from tests.integration.helpers.helpers import (
    CLIENT_APP_NAME,
    PG,
    PGB,
)

logger = logging.getLogger(__name__)

DATA_INTEGRATOR_APP_NAME = "data-integrator"
CLIENT_UNIT_NAME = f"{CLIENT_APP_NAME}/0"
TEST_DBNAME = "postgresql_test_app_first_database"
ANOTHER_APPLICATION_APP_NAME = "another-application"
PG_2 = "another-postgresql"
PGB_2 = "another-pgbouncer"
APP_NAMES = [CLIENT_APP_NAME, PG]
MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME = "multiple-database-clusters"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_database_relation_with_charm_libraries(ops_test: OpsTest, pgb_charm_jammy):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                CLIENT_APP_NAME,
                application_name=CLIENT_APP_NAME,
                channel="edge",
            ),
            ops_test.model.deploy(
                pgb_charm_jammy,
                application_name=PGB,
                num_units=None,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel="14/edge",
                config={"profile": "testing"},
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.wait_for_idle(status="active", timeout=600)


@pytest.mark.group(1)
async def test_relation_with_data_integrator(ops_test: OpsTest):
    """Test that the charm can be related to the data integrator without extra user roles."""
    config = {"database-name": "test-database"}
    await ops_test.model.deploy(
        DATA_INTEGRATOR_APP_NAME,
        channel="edge",
        config=config,
    )
    await ops_test.model.add_relation(f"{PGB}:database", DATA_INTEGRATOR_APP_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(status="active")
