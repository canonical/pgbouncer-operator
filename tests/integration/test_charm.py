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
    cores = int(await get_unit_cores(unit))

    expected_cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
    expected_cfg["pgbouncer"]["pool_mode"] = "transaction"
    expected_cfg.set_max_db_connection_derivatives(44, cores)

    primary_cfg = await pull_content_from_unit_file(unit, INI_PATH)
    existing_cfg = pgb.PgbConfig(primary_cfg)

    TestCase().assertDictEqual(dict(existing_cfg), dict(expected_cfg))

    # Validating service config files are correctly written is handled by _render_service_config
    # and its tests, but we need to make sure they at least exist in the right places.
    for service in range(2000, 2000 + cores):
        path = f"{PGB_DIR}/instance_{service}/pgbouncer.ini"
        service_cfg = await pull_content_from_unit_file(unit, path)
        assert service_cfg is not f"cat: {path}: No such file or directory"


async def test_systemd_restarts_pgbouncer_processes(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    expected_processes = await get_unit_cores(unit)

    # verify the correct amount of pgbouncer processes are running
    assert await get_running_instances(unit, "pgbouncer") == expected_processes

    # Kill pgbouncer process and wait for it to restart
    await unit.run("kill $(ps aux | grep pgbouncer | awk '{print $2}')")
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=300)

    # verify all processes start again
    assert await get_running_instances(unit, "pgbouncer") == expected_processes


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


async def get_unit_cores(unit: str) -> int:
    """Get the number of CPU cores available on the given unit.

    Since PgBouncer is single-threaded, the charm automatically creates one instance of pgbouncer
    per CPU core on a given unit. Therefore, the number of cores is the expected number of
    pgbouncer instances.

    Args:
        unit: the juju unit instance
    Returns:
        The number of cores on the unit.
    """
    get_cores_action = await unit.run('python3 -c "import os; print(os.cpu_count())"')
    cores = get_cores_action.results.get("Stdout")
    return int(cores)

async def get_running_instances(unit: str, service: str) -> int:
    """Returns the number of running instances of the given service.

    Uses `ps` to find the number of instances of a given service.

    Args:
        unit: the juju unit running the service
        service: a string that can be used to grep for the intended service.
    Returns:
        an integer defining the number of running instances.
    """
    get_running_instances = await unit.run(f"ps aux | grep {service}")
    ps_output = get_running_instances.results.get("Stdout")
    num_of_ps_lines = len(ps_output.split("\n"))
    # one extra for grep process, and one for a blank line at the end
    return num_of_ps_lines - 2