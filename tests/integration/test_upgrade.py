#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Union

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from .helpers.ha_helpers import (
    are_writes_increasing,
    check_writes,
    start_continuous_writes,
)
from .helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
)
from .helpers.postgresql_helpers import get_leader_unit
from .relations.pgbouncer_provider.helpers import (
    get_application_relation_data,
)

logger = logging.getLogger(__name__)

TIMEOUT = 600


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy_latest(ops_test: OpsTest, pgb_charm_jammy) -> None:
    """Simple test to ensure that the PostgreSQL and application charms get deployed."""
    await asyncio.gather(
        ops_test.model.deploy(
            PG,
            num_units=3,
            channel="14/edge",
            config={"profile": "testing"},
        ),
        ops_test.model.deploy(
            PGB,
            channel="1/edge",
            num_units=None,
        ),
        ops_test.model.deploy(
            CLIENT_APP_NAME,
            num_units=3,
            channel="latest/edge",
        ),
    )
    logger.info("Wait for applications to become active")

    await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[PG, PGB, CLIENT_APP_NAME], status="active", timeout=1500
        )
    assert len(ops_test.model.applications[PG].units) == 3
    assert len(ops_test.model.applications[PGB].units) == 3


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check(ops_test: OpsTest) -> None:
    """Test that the pre-upgrade-check action runs successfully."""
    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, PGB)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_upgrade_from_edge(ops_test: OpsTest, continuous_writes, pgb_charm_jammy) -> None:
    # Start an application that continuously writes data to the database.
    logger.info("starting continuous writes to the database")
    await start_continuous_writes(ops_test, PGB)

    # Check whether writes are increasing.
    logger.info("checking whether writes are increasing")
    await are_writes_increasing(ops_test)

    application = ops_test.model.applications[PGB]

    logger.info("Refresh the charm")
    await application.refresh(path=pgb_charm_jammy)

    logger.info("Wait for upgrade to start")
    await ops_test.model.block_until(
        lambda: "waiting" in {unit.workload_status for unit in application.units},
        timeout=TIMEOUT,
    )

    logger.info("Wait for upgrade to complete")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(
            apps=[PGB], status="active", idle_period=30, timeout=TIMEOUT
        )

    # Check whether writes are increasing.
    logger.info("checking whether writes are increasing")
    await are_writes_increasing(ops_test)

    # Verify that no writes to the database were missed after stopping the writes
    # (check that all the units have all the writes).
    logger.info("checking whether no writes were lost")
    await check_writes(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_fail_and_rollback(ops_test, continuous_writes, pgb_charm_jammy) -> None:
    # Start an application that continuously writes data to the database.
    logger.info("starting continuous writes to the database")
    await start_continuous_writes(ops_test, PGB)

    # Check whether writes are increasing.
    logger.info("checking whether writes are increasing")
    await are_writes_increasing(ops_test)

    logger.info("Get leader unit")
    leader_unit = await get_leader_unit(ops_test, PGB)
    assert leader_unit is not None, "No leader unit found"

    logger.info("Run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    if isinstance(pgb_charm_jammy, str):
        filename = pgb_charm_jammy.split("/")[-1]
    else:
        filename = pgb_charm_jammy.name
    fault_charm = Path("/tmp/", filename)
    shutil.copy(pgb_charm_jammy, fault_charm)

    logger.info("Inject dependency fault")
    await inject_dependency_fault(ops_test, PGB, fault_charm)

    application = ops_test.model.applications[PGB]

    logger.info("Refresh the charm")
    await application.refresh(path=fault_charm)

    logger.info("Wait for upgrade to fail")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.block_until(
            lambda: "blocked" in {unit.workload_status for unit in application.units},
            timeout=TIMEOUT,
        )

    logger.info("Ensure continuous_writes while in failure state on remaining units")
    await are_writes_increasing(ops_test)

    logger.info("Re-run pre-upgrade-check action")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    logger.info("Re-refresh the charm")
    await application.refresh(path=pgb_charm_jammy)

    logger.info("Wait for upgrade to start")
    await ops_test.model.block_until(
        lambda: "waiting" in {unit.workload_status for unit in application.units},
        timeout=TIMEOUT,
    )

    logger.info("Wait for application to recover")
    async with ops_test.fast_forward("60s"):
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=TIMEOUT)

    logger.info("Ensure continuous_writes after rollback procedure")
    await are_writes_increasing(ops_test)

    # Verify that no writes to the database were missed after stopping the writes
    # (check that all the units have all the writes).
    logger.info("Checking whether no writes were lost")
    await check_writes(ops_test)

    # Remove fault charm file.
    fault_charm.unlink()


async def inject_dependency_fault(
    ops_test: OpsTest, application_name: str, charm_file: Union[str, Path]
) -> None:
    """Inject a dependency fault into the PostgreSQL charm."""
    # Query running dependency to overwrite with incompatible version.
    dependencies = await get_application_relation_data(
        ops_test, application_name, "upgrade", "dependencies"
    )
    loaded_dependency_dict = json.loads(dependencies)
    if "snap" not in loaded_dependency_dict:
        loaded_dependency_dict["snap"] = {"dependencies": {}, "name": "charmed-postgresql"}
    loaded_dependency_dict["snap"]["upgrade_supported"] = "^15"
    loaded_dependency_dict["snap"]["version"] = "15.0"

    # Overwrite dependency.json with incompatible version.
    with zipfile.ZipFile(charm_file, mode="a") as charm_zip:
        charm_zip.writestr("src/dependency.json", json.dumps(loaded_dependency_dict))
