#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from charms.pgbouncer_k8s.v0.pgb import DEFAULT_CONFIG, PgbConfig
from pytest_operator.plugin import OpsTest

from constants import PGB_DIR
from tests.integration.helpers import helpers

logger = logging.getLogger(__name__)

CLIENT_APP_NAME = "application"
FIRST_DATABASE_RELATION_NAME = "first-database"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]

WAIT_MSG = "waiting for backend database relation to connect"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, application_charm, pgb_charm_jammy):
    """Build and deploy the charm-under-test.

    Assert on the unit status before any relations/configurations take place.
    """
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(application_charm, application_name=CLIENT_APP_NAME),
            ops_test.model.deploy(
                pgb_charm_jammy,
                application_name=PGB,
                num_units=None,
            ),
        )
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
        # Pgbouncer enters a blocked status without a postgres backend database relation
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)
    assert ops_test.model.units[f"{PGB}/0"].workload_status_message == WAIT_MSG


async def test_change_config(ops_test: OpsTest):
    """Change config and assert that the pgbouncer config file looks how we expect."""
    async with ops_test.fast_forward():
        unit = ops_test.model.units[f"{PGB}/0"]
        await ops_test.model.applications[PGB].set_config(
            {
                "pool_mode": "transaction",
                "max_db_connections": "44",
            }
        )
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)
    assert ops_test.model.units[f"{PGB}/0"].workload_status_message == WAIT_MSG

    # The config changes depending on the amount of cores on the unit, so get that info.
    cores = await helpers.get_unit_cores(unit)

    expected_cfg = PgbConfig(DEFAULT_CONFIG)
    expected_cfg["pgbouncer"]["pool_mode"] = "transaction"
    expected_cfg.set_max_db_connection_derivatives(44, cores)

    primary_cfg = await helpers.get_cfg(ops_test, unit.name)
    existing_cfg = PgbConfig(primary_cfg)

    assert existing_cfg.render() == primary_cfg.render()

    # Validating service config files are correctly written is handled by render_pgb_config and its
    # tests, but we need to make sure they at least exist in the right places.
    for service_id in range(cores):
        path = f"{PGB_DIR}/instance_{service_id}/pgbouncer.ini"
        service_cfg = await helpers.get_cfg(ops_test, unit.name, path=path)
        assert service_cfg is not f"cat: {path}: No such file or directory"


async def test_systemd_restarts_pgbouncer_processes(ops_test: OpsTest):
    unit = ops_test.model.units[f"{PGB}/0"]
    expected_processes = await helpers.get_unit_cores(unit)

    # verify the correct amount of pgbouncer processes are running
    assert await helpers.get_running_instances(unit, "pgbouncer") == expected_processes

    # Kill pgbouncer process and wait for it to restart
    await unit.run("kill $(pgrep pgbouncer)")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=(3 * 60))
    assert ops_test.model.units[f"{PGB}/0"].workload_status_message == WAIT_MSG

    # verify all processes start again
    assert await helpers.get_running_instances(unit, "pgbouncer") == expected_processes
