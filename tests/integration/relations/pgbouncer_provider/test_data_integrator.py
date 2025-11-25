#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME, PGB_CONF_DIR

from ...helpers.helpers import (
    PG,
    PGB,
    get_cfg,
    get_unit_cores,
)
from ...juju_ import juju_major_version
from .helpers import (
    DATA_INTEGRATOR_APP_NAME,
    check_exposed_connection,
    fetch_action_get_credentials,
)

logger = logging.getLogger(__name__)

if juju_major_version < 3:
    tls_certificates_app_name = "tls-certificates-operator"
    tls_channel = "legacy/stable"
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
else:
    tls_certificates_app_name = "self-signed-certificates"
    tls_channel = "1/stable"
    tls_config = {"ca-common-name": "Test CA"}


@pytest.mark.abort_on_fail
async def test_deploy_and_relate(ops_test: OpsTest, charm_noble):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    config = {"database-name": "test-database"}
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm_noble, application_name=PGB, num_units=0, base="ubuntu@24.04"
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
                config={"profile": "testing"},
            ),
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                channel="edge",
                num_units=2,
                config=config,
                base="ubuntu@24.04",
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


async def test_add_tls(ops_test: OpsTest, charm):
    await ops_test.model.add_relation(PGB, tls_certificates_app_name)
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, True)


async def test_remove_tls(ops_test: OpsTest, charm):
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:certificates", f"{tls_certificates_app_name}:certificates"
    )
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)


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
