#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
import os
from pathlib import Path
from unittest import TestCase

import pytest
import yaml
from charms.pgbouncer_operator.v0 import pgb
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

PGB_DIR = "/etc/pgbouncer"
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
    await ops_test.model.applications["pgbouncer-operator"].set_config(
        {
            "pool_mode": "transaction",
            "max_db_connections": "44",
        }
    )
    # Assert pgbouncer.ini is what we expect
    logger.info(ops_test.model.units)
    unit = ops_test.model.units["pgbouncer-operator/0"]
    pgb_ini = await pull_content_from_unit_file(unit, INI_PATH)
    logging.info(pgb_ini)
    existing_pgb_ini = pgb.PgbConfig(pgb_ini)
    expected_pgb_ini = pgb.PgbConfig(
        {
            "databases": {},
            "pgbouncer": {
                "logfile": "/etc/pgbouncer/pgbouncer.log",
                "pidfile": "/etc/pgbouncer/pgbouncer.pid",
                "admin_users": ["juju-admin"],
                "max_client_conn": "10000",
                "ignore_startup_parameters": "extra_float_digits",
                "pool_mode": "transaction",
            },
        }
    )
    expected_pgb_ini.set_max_db_connection_derivatives(
        44,
        os.cpu_count(),
    )
    logging.info(dict(existing_pgb_ini))
    logging.info(dict(expected_pgb_ini))
    TestCase().assertDictEqual(dict(existing_pgb_ini), dict(expected_pgb_ini))


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
