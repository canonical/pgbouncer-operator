#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os

import psycopg2
import psycopg2.sql
import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ... import markers
from ...helpers.helpers import (
    PG,
    PGB,
)
from .helpers import (
    DATA_INTEGRATOR_APP_NAME,
    build_connection_string,
    check_connected_user,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_deploy(ops_test: OpsTest, charm_noble):
    """Deploy the postgresql charm along with data integrator charm."""
    async with ops_test.fast_forward("10s"):
        await asyncio.gather(
            ops_test.model.deploy(
                charm_noble, application_name=PGB, num_units=0, base="ubuntu@24.04"
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
                base="ubuntu@24.04",
                config={"profile": "testing"},
            ),
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                channel="edge",
                base="ubuntu@24.04",
            ),
        )

        await ops_test.model.add_relation(PG, PGB)
        await ops_test.model.wait_for_idle(apps=[PG], status="active")
        assert ops_test.model.applications[PG].units[0].workload_status == "active"
        await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked")


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_charmed_dba_role(ops_test: OpsTest):
    """Test the DBA predefined role."""
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].set_config({
        "database-name": "charmed_dba_database",
        "extra-user-roles": "charmed_dba",
    })
    await ops_test.model.add_relation(DATA_INTEGRATOR_APP_NAME, PGB)
    await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    action = await ops_test.model.units[f"{DATA_INTEGRATOR_APP_NAME}/0"].run_action(
        action_name="get-credentials"
    )
    result = await action.wait()
    data_integrator_credentials = result.results
    username = data_integrator_credentials["postgresql"]["username"]

    for read_write_endpoint in [True, False]:
        connection_string = await build_connection_string(
            ops_test,
            DATA_INTEGRATOR_APP_NAME,
            "postgresql",
            database="charmed_dba_database",
            read_only_endpoint=(not read_write_endpoint),
            port=6432,
        )
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3), reraise=True):
            with attempt:
                connection = psycopg2.connect(connection_string)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                instance = "primary" if read_write_endpoint else "replica"
                logger.info(f"Resetting the user to the {username} user in the {instance}")
                cursor.execute("RESET ROLE;")
                check_connected_user(cursor, username, username, primary=read_write_endpoint)
                logger.info(f"Testing escalation to the rewind user in the {instance}")
                cursor.execute("SELECT set_user('rewind'::TEXT);")
                check_connected_user(cursor, username, "rewind", primary=read_write_endpoint)
                logger.info(f"Resetting the user to the {username} user in the {instance}")
                cursor.execute("SELECT reset_user();")
                check_connected_user(cursor, username, username, primary=read_write_endpoint)
                logger.info(f"Testing escalation to the operator user in the {instance}")
                cursor.execute("SELECT set_user_u('operator'::TEXT);")
                check_connected_user(cursor, username, "operator", primary=read_write_endpoint)
                logger.info(f"Resetting the user to the {username} user in the {instance}")
                cursor.execute("SELECT reset_user();")
                check_connected_user(cursor, username, username, primary=read_write_endpoint)
        finally:
            if connection is not None:
                connection.close()
