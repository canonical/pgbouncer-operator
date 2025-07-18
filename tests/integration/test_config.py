#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
from asyncio import gather

import pytest as pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from .helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_config_parameters(ops_test: OpsTest, charm) -> None:
    """Build and deploy one unit of PostgreSQL and then test config with wrong parameters."""
    # Build and deploy the PostgreSQL charm.
    async with ops_test.fast_forward():
        await gather(
            ops_test.model.deploy(
                CLIENT_APP_NAME,
                application_name=CLIENT_APP_NAME,
                channel="edge",
            ),
            ops_test.model.deploy(
                charm,
                application_name=PGB,
                num_units=0,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=1,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
                config={"profile": "testing"},
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG, CLIENT_APP_NAME], timeout=1200)
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)

    await ops_test.model.wait_for_idle(status="active", timeout=600)

    unit = ops_test.model.applications[PGB].units[0]
    test_string = "abcXYZ123"

    configs = {
        "listen_port": "0",
        "metrics_port": "0",
        "vip": test_string,
        "local_connection_type": test_string,
        "pool_mode": test_string,
        "max_db_connections": "-1",
    }

    for key, val in configs.items():
        logger.info(key)
        await ops_test.model.applications[PGB].set_config({key: val})
        await ops_test.model.block_until(
            lambda: ops_test.model.units[f"{PGB}/0"].workload_status == "blocked",
            timeout=100,
        )
        assert "Configuration Error" in unit.workload_status_message

        await ops_test.model.applications[PGB].reset_config([key])
        await ops_test.model.block_until(
            lambda: ops_test.model.units[f"{PGB}/0"].workload_status == "active",
            timeout=100,
        )
