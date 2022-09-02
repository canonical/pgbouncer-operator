# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import helpers

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"
PSQL = "psql"
APPS = [PG, PGB, PSQL]
BUILT_CHARM = None

# TODO update to use different charms for testing


@pytest.mark.abort_on_fail
@pytest.mark.legacy_relation
async def test_create_db_admin_legacy_relation(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    charm = await ops_test.build_charm(".")
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=PGB,
            ),
            ops_test.model.deploy(PG, channel="edge", trust=True, num_units=3),
            # Deploy a psql client shell charm
            ops_test.model.deploy("postgresql-charmers-postgresql-client", application_name=PSQL),
        )
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000),
            ops_test.model.wait_for_idle(apps=[PGB, PSQL], status="blocked", timeout=1000),
        )
        await ops_test.model.add_relation(f"{PGB}:backend-database", f"{PG}:database"),

        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PG, PGB], status="active", timeout=1000),
            ops_test.model.wait_for_idle(apps=[PSQL], status="blocked", timeout=1000),
        )
        await ops_test.model.add_relation(f"{PGB}:db-admin", f"{PSQL}:db"),
        await ops_test.model.wait_for_idle(apps=APPS, status="active", timeout=1000)

    unit = ops_test.model.units[f"{PGB}/0"]
    cfg = await helpers.get_cfg(ops_test, unit.name)
    assert "cli" in cfg["databases"].keys()


@pytest.mark.legacy_relation
async def test_add_replicas(ops_test: OpsTest):
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=1000, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[PSQL], status="active", timeout=1000, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(apps=[PGB], status="active"),
        )
    unit = ops_test.model.units[f"{PGB}/0"]
    cfg = await helpers.get_cfg(ops_test, unit.name)
    expected_databases = ["cli", "cli_standby"]
    for database in expected_databases:
        assert database in cfg["databases"].keys()


@pytest.mark.legacy_relation
async def test_remove_db_admin_leader(ops_test: OpsTest):
    await ops_test.model.destroy_unit("psql/0")
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PSQL], status="active", timeout=1000),
            ops_test.model.wait_for_idle(
                apps=[PG, PGB],
                status="active",
                timeout=1000,
            ),
        )
    unit = ops_test.model.units[f"{PGB}/0"]
    cfg = await helpers.get_cfg(ops_test, unit.name)
    assert "cli" in cfg["databases"].keys()


@pytest.mark.legacy_relation
async def test_remove_backend_leader(ops_test: OpsTest):
    await ops_test.model.destroy_unit("postgresql/0")
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000),
            ops_test.model.wait_for_idle(apps=[PGB, PSQL], status="active", timeout=1000),
        )
    unit = ops_test.model.units[f"{PGB}/0"]
    cfg = await helpers.get_cfg(ops_test, unit.name)
    assert "cli" in cfg["databases"].keys()


@pytest.mark.legacy_relation
async def test_remove_db_admin_legacy_relation(ops_test: OpsTest):
    """Test that removing relations still works ok."""
    await ops_test.model.applications[PGB].remove_relation(f"{PGB}:db-admin", f"{PSQL}:db")
    await ops_test.model.applications[PSQL].remove()
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[PGB, PG], status="active", timeout=1000)

    unit = ops_test.model.units[f"{PGB}/0"]
    cfg = await helpers.get_cfg(ops_test, unit.name)
    assert "cli" not in cfg["databases"].keys()
