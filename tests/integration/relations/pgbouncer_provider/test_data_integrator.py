#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from typing import Dict

import pytest
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME, PGB_CONF_DIR

from ... import architecture
from ...helpers.helpers import (
    PG,
    PGB,
    get_cfg,
    get_unit_cores,
)
from ...juju_ import juju_major_version
from .helpers import check_exposed_connection

logger = logging.getLogger(__name__)

DATA_INTEGRATOR_APP_NAME = "data-integrator"

if juju_major_version < 3:
    tls_certificates_app_name = "tls-certificates-operator"
    if architecture.architecture == "arm64":
        tls_channel = "legacy/edge"
    else:
        tls_channel = "legacy/stable"
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
else:
    tls_certificates_app_name = "self-signed-certificates"
    if architecture.architecture == "arm64":
        tls_channel = "latest/edge"
    else:
        tls_channel = "latest/stable"
    tls_config = {"ca-common-name": "Test CA"}


async def fetch_action_get_credentials(unit: Unit) -> Dict:
    """Helper to run an action to fetch connection info.

    Args:
        unit: The juju unit on which to run the get_credentials action for credentials
    Returns:
        A dictionary with the username, password and access info for the service
    """
    action = await unit.run_action(action_name="get-credentials")
    result = await action.wait()
    return result.results


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_and_relate(ops_test: OpsTest, pgb_charm_jammy):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    config = {"database-name": "test-database"}
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
                num_units=2,
                config=config,
            ),
            ops_test.model.deploy(
                tls_certificates_app_name, config=tls_config, channel=tls_channel
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")

    await ops_test.model.add_relation(PGB, DATA_INTEGRATOR_APP_NAME)
    await ops_test.model.wait_for_idle(status="active", timeout=1200)

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)


@pytest.mark.group(1)
async def test_add_tls(ops_test: OpsTest, pgb_charm_jammy):
    await ops_test.model.add_relation(PGB, tls_certificates_app_name)
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, True)


@pytest.mark.group(1)
async def test_remove_tls(ops_test: OpsTest, pgb_charm_jammy):
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:certificates", f"{tls_certificates_app_name}:certificates"
    )
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)


@pytest.mark.group(1)
async def test_change_config(ops_test: OpsTest):
    """Change config and assert that the pgbouncer config file looks how we expect."""
    async with ops_test.fast_forward():
        unit = ops_test.model.units[f"{PGB}/0"]
        await ops_test.model.applications[PGB].set_config({
            "pool_mode": "transaction",
            "max_db_connections": "44",
        })
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=600)

    # The config changes depending on the amount of cores on the unit, so get that info.
    cores = max(min(await get_unit_cores(ops_test, unit), 4), 2)

    primary_cfg = await get_cfg(ops_test, unit.name)

    assert primary_cfg["pgbouncer"]["pool_mode"] == "transaction"
    assert primary_cfg["pgbouncer"]["max_db_connections"] == "44"

    # Validating service config files are correctly written is handled by render_pgb_config and its
    # tests, but we need to make sure they at least exist in the right places.
    for service_id in range(cores):
        path = f"{PGB_CONF_DIR}/{PGB}/instance_{service_id}/pgbouncer.ini"
        service_cfg = await get_cfg(ops_test, unit.name, path=path)
        assert service_cfg is not f"cat: {path}: No such file or directory"
