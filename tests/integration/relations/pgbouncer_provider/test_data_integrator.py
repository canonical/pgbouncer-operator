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

# DATA_INTEGRATOR_APP_NAME = "data-integrator"
# TODO replace with data-integrator once it can handle secrets
DATA_INTEGRATOR_APP_NAME = CLIENT_APP_NAME


# TODO remove when we no longer need to hotpatch
async def _update_file(ops_test: OpsTest, file_path, dest):
    unit = ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    base_path = f"/var/lib/juju/agents/unit-{unit.name.replace('/', '-').replace('_', '-')}/charm"
    await unit.scp_to(source=file_path, destination="temp_file")
    mv_cmd = f"exec --unit {unit.name} sudo mv /home/ubuntu/temp_file {base_path}/{dest}"
    return_code, _, _ = await ops_test.juju(*mv_cmd.split())
    assert return_code == 0
    chown_cmd = f"exec --unit {unit.name} sudo chown root:root {base_path}/{dest}"
    return_code, _, _ = await ops_test.juju(*chown_cmd.split())
    assert return_code == 0
    chmod_cmd = f"exec --unit {unit.name} sudo chmod +x {base_path}/{dest}"
    return_code, _, _ = await ops_test.juju(*chmod_cmd.split())
    assert return_code == 0


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_and_relate(ops_test: OpsTest, pgb_charm_jammy):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    # config = {"database-name": "test-database"}
    async with ops_test.fast_forward():
        await asyncio.gather(
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
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                channel="edge",
                # config=config,
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    # TODO remove hotpatching when data-integrator implements its side of the replation
    await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME])
    await _update_file(
        ops_test,
        "./lib/charms/data_platform_libs/v0/data_interfaces.py",
        "lib/charms/data_platform_libs/v0/data_interfaces.py",
    )
    await _update_file(
        ops_test,
        "./tests/integration/relations/pgbouncer_provider/data_integrator_charm.py",
        "src/charm.py",
    )

    # await ops_test.model.add_relation(PGB, DATA_INTEGRATOR_APP_NAME)
    await ops_test.model.add_relation(PGB, f"{DATA_INTEGRATOR_APP_NAME}:first-database")
    await ops_test.model.wait_for_idle(status="active")
