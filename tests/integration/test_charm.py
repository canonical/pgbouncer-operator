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

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

PGB_DIR = "/var/lib/postgresql/pgbouncer"
INI_PATH = f"{PGB_DIR}/pgbouncer.ini"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(
        charm,
        application_name=APP_NAME,
    )
    # pgbouncer start command has to be successful for status to be active, and it fails if config
    # is invalid. However, this will be tested further once health monitoring is implemented.
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)


async def test_change_config(ops_test: OpsTest):
    """Change config and assert that the pgbouncer config file looks how we expect."""
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.applications["pgbouncer-operator"].set_config(
        {
            "pool_mode": "transaction",
            "max_db_connections": "44",
        }
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    # The config changes depending on the amount of cores on the unit, so get that info.
    get_cores_action = await unit.run('python3 -c "import os; print(os.cpu_count())"')
    cores = get_cores_action.results.get("Stdout")

    expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
    expected_cfg["pgbouncer"]["pool_mode"] = "transaction"
    expected_cfg.set_max_db_connection_derivatives(44, int(cores))

    cfg = await pull_content_from_unit_file(unit, INI_PATH)
    existing_cfg = pgb.PgbConfig(cfg)

    TestCase().assertDictEqual(dict(existing_cfg), dict(expected_cfg))


async def test_systemd_restarts_pgbouncer_process(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    # Kill pgbouncer process and wait for it to restart
    await unit.run("kill $(ps aux | grep pgbouncer | awk '{print $2}')")
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=300)


async def pull_content_from_unit_file(unit, path: str) -> str:
    """Pull the content of a file from one unit.

    Args:
        unit: the Juju unit instance.
        path: the path of the file to get the contents from.

    Returns:
        the entire content of the file.
    """
    action = await unit.run(f"cat {path}")
    return action.results.get("Stdout", None)
