#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME, PGB_CONF_DIR, PGB_LOG_DIR

from .helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
    WAIT_MSG,
    get_cfg,
    get_running_instances,
    get_unit_cores,
)
from .helpers.postgresql_helpers import restart_machine

logger = logging.getLogger(__name__)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, pgb_charm_jammy):
    """Build and deploy the charm-under-test.

    Assert on the unit status before any relations/configurations take place.
    """
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                CLIENT_APP_NAME, application_name=CLIENT_APP_NAME, channel="edge"
            ),
            ops_test.model.deploy(
                pgb_charm_jammy,
                application_name=PGB,
                num_units=None,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                channel="14/edge",
                config={"profile": "testing"},
            ),
        )
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
        # Pgbouncer enters a blocked status without a postgres backend database relation
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600)
        assert ops_test.model.units[f"{PGB}/0"].workload_status_message == WAIT_MSG

        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")

        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=600)


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


@pytest.mark.group(1)
async def test_systemd_restarts_pgbouncer_processes(ops_test: OpsTest):
    unit = ops_test.model.units[f"{PGB}/0"]
    expected_processes = max(min(await get_unit_cores(ops_test, unit), 4), 2)

    # verify the correct amount of pgbouncer processes are running
    assert await get_running_instances(ops_test, unit, "pgbouncer") == expected_processes

    # Kill pgbouncer process and wait for it to restart
    await unit.run("pkill -SIGINT -x pgbouncer")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=(3 * 60))

    # verify all processes start again
    assert await get_running_instances(ops_test, unit, "pgbouncer") == expected_processes


@pytest.mark.group(1)
async def test_systemd_restarts_exporter_process(ops_test: OpsTest):
    unit = ops_test.model.units[f"{PGB}/0"]

    # verify the correct amount of pgbouncer_exporter processes are running
    assert await get_running_instances(ops_test, unit, "pgbouncer_expor") == 1

    # Kill pgbouncer_exporter process and wait for it to restart
    await unit.run("pkill -SIGTERM -x pgbouncer_expor")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=(3 * 60))

    # verify all processes start again
    assert await get_running_instances(ops_test, unit, "pgbouncer_expor") == 1


@pytest.mark.group(1)
async def test_logrotate(ops_test: OpsTest):
    """Verify that logs will be rotated."""
    unit = ops_test.model.units[f"{PGB}/0"]
    await unit.run("logrotate -f /etc/logrotate.conf")

    cmd = f"ssh {PGB}/0 sudo ls {PGB_LOG_DIR}/{PGB}/instance_0"
    return_code, output, _ = await ops_test.juju(*cmd.split(" "))
    assert return_code == 0
    logs = output.strip().split()
    logs.remove("pgbouncer.log")
    assert len(logs), "Log not rotated"


@pytest.mark.group(1)
async def test_restart_unit(ops_test: OpsTest):
    await restart_machine(ops_test, f"{CLIENT_APP_NAME}/0")

    await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=600)
