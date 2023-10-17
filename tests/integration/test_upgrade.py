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
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
)
from tests.integration.relations.pgbouncer_provider.helpers import (
    check_new_relation,
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


@pytest.mark.abort_on_fail
async def test_in_place_upgrade(ops_test: OpsTest, pgb_charm_jammy):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    logger.info("Deploying PGB...")
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
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG, CLIENT_APP_NAME], timeout=1200)
        # Relate the charms and wait for them exchanging some connection data.
        global client_relation
        client_relation = await ops_test.model.add_relation(
            f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB
        )

    await ops_test.model.wait_for_idle(status="active", timeout=600)

    # This test hasn't passed if we can't pass a tiny amount of data through the new relation
    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )

    leader = None
    for unit in ops_test.model.applications[PGB].units:
        if await unit.is_leader_from_status():
            leader = unit
            break

    action = await leader.run_action("pre-upgrade-check")
    await action.wait()

    await ops_test.model.wait_for_idle(apps=APP_NAMES, status="active", raise_on_blocked=True)

    logger.info("Upgrading PGB...")
    await ops_test.model.applications[PGB].refresh(path=pgb_charm_jammy)
    await ops_test.model.wait_for_idle(apps=[PGB], status="active", raise_on_blocked=True)

    action = await leader.run_action("resume-upgrade")
    await action.wait()

    await ops_test.model.wait_for_idle(apps=[PGB], status="active", raise_on_blocked=True)

    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )
