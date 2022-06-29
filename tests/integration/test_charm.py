#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path
from unittest import TestCase

import pytest
import yaml
from charms.pgbouncer_operator.v0 import pgb
from pytest_operator.plugin import OpsTest

from tests.integration import helpers

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

PGB_DIR = pgb.PGB_DIR
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"


@pytest.mark.abort_on_fail
@pytest.mark.smoke
async def test_build_and_deploy_current(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(
        charm,
        application_name=APP_NAME,
    )
    # Pgbouncer enters a blocked status without a postgres backend database relation
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000)
    assert (
        ops_test.model.units[f"{APP_NAME}/0"].workload_status_message
        == "waiting for backend database relation"
    )


async def test_change_config(ops_test: OpsTest):
    """Change config and assert that the pgbouncer config file looks how we expect."""
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.applications[APP_NAME].set_config(
        {
            "pool_mode": "transaction",
            "max_db_connections": "44",
        }
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000)
    assert (
        ops_test.model.units[f"{APP_NAME}/0"].workload_status_message
        == "waiting for backend database relation"
    )

    # The config changes depending on the amount of cores on the unit, so get that info.
    cores = await helpers.get_unit_cores(unit)

    expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
    expected_cfg["pgbouncer"]["pool_mode"] = "transaction"
    expected_cfg.set_max_db_connection_derivatives(44, cores)

    primary_cfg = await helpers.get_cfg(unit)
    existing_cfg = pgb.PgbConfig(primary_cfg)

    TestCase().assertDictEqual(dict(existing_cfg), dict(expected_cfg))

    # Validating service config files are correctly written is handled by _render_service_config
    # and its tests, but we need to make sure they at least exist in the right places.
    for service_id in range(cores):
        path = f"{PGB_DIR}/instance_{service_id}/pgbouncer.ini"
        service_cfg = await helpers.cat_from(unit, path)
        assert service_cfg is not f"cat: {path}: No such file or directory"


async def test_systemd_restarts_pgbouncer_processes(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    expected_processes = await helpers.get_unit_cores(unit)

    # verify the correct amount of pgbouncer processes are running
    assert await helpers.get_running_instances(unit, "pgbouncer") == expected_processes

    # Kill pgbouncer process and wait for it to restart
    await unit.run("kill $(ps aux | grep pgbouncer | awk '{print $2}')")
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=300)
    assert (
        ops_test.model.units[f"{APP_NAME}/0"].workload_status_message
        == "waiting for backend database relation"
    )

    # verify all processes start again
    assert await helpers.get_running_instances(unit, "pgbouncer") == expected_processes
