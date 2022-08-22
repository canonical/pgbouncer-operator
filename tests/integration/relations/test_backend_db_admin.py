# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration import helpers

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
POSTGRESQL = "postgresql"


@pytest.mark.abort_on_fail
@pytest.mark.legacy_relations
@pytest.mark.backend
async def test_create_backend_db_admin_legacy_relation(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    charm = await ops_test.build_charm(".")
    with await ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=APP_NAME,
            ),
            ops_test.model.deploy(POSTGRESQL),
        )

        # Pgbouncer enters a blocked state without backend postgres relation
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000)
        await ops_test.model.add_relation(f"{APP_NAME}:backend-db-admin", f"{POSTGRESQL}:db-admin")
        await ops_test.model.wait_for_idle(apps=[APP_NAME, POSTGRESQL], status="active", timeout=1000)

    unit = ops_test.model.units["pgbouncer-operator/0"]
    cfg = await helpers.get_cfg(unit)
    # When there's only one postgres unit, we're in "standalone" mode with no standby replicas.
    assert list(cfg["databases"].keys()) == ["pg_master"]


@pytest.mark.legacy_relations
@pytest.mark.backend
async def test_backend_db_admin_legacy_relation_scale_up(ops_test: OpsTest):
    """Test that the pgbouncer config accurately reflects postgres replication changes.

    Requires existing deployed pgbouncer and legacy postgres charms, connected by a
    backend-db-admin relation
    """
    unit = ops_test.model.units["pgbouncer-operator/0"]
    with await ops_test.fast_forward():
        await ops_test.model.applications[POSTGRESQL].add_units(count=2)
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[POSTGRESQL], status="active", timeout=1000, wait_for_exact_units=3
            ),
            ops_test.model.wait_for_idle(
                apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
            ),
        )
    cfg = await helpers.get_cfg(unit)
    # Now there are three postgres units, we're in "standby" mode, with two standby replicas.
    assert list(cfg["databases"].keys()) == [
        "pg_master",
        "pgb_postgres_standby_0",
        "pgb_postgres_standby_1",
    ]


@pytest.mark.legacy_relations
@pytest.mark.backend
async def test_backend_db_admin_legacy_relation_scale_down(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.destroy_unit("postgresql/1")
    with await ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[POSTGRESQL], status="active", timeout=1000, wait_for_exact_units=2
            ),
            ops_test.model.wait_for_idle(
                apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
            ),
        )
    cfg = await helpers.get_cfg(unit)
    # Now there are two postgres units, and the config reflects this. The standby index is just an
    # index, and isn't linked to the unit name.
    assert list(cfg["databases"].keys()) == ["pg_master", "pgb_postgres_standby_0"]
    assert "pgb_postgres_standby_1" not in cfg["databases"].keys()


@pytest.mark.legacy_relations
@pytest.mark.backend
async def test_backend_db_admin_legacy_relation_delete_postgres_leader(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.destroy_unit("postgresql/0")
    with await ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(
                apps=[POSTGRESQL], status="active", timeout=1000, wait_for_exact_units=1
            ),
            ops_test.model.wait_for_idle(
                apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
            ),
        )
    cfg = await helpers.get_cfg(unit)
    # Now there is only one config, with no replicas, and the config reflects this.
    assert list(cfg["databases"].keys()) == ["pg_master"]
    assert "pgb_postgres_standby_0" not in cfg["databases"].keys()


@pytest.mark.legacy_relations
@pytest.mark.backend
async def test_backend_db_admin_legacy_relation_remove_relation(ops_test: OpsTest):
    unit = ops_test.model.units["pgbouncer-operator/0"]
    # Remove relation but keep pg application because we're going to need it for future tests.
    await ops_test.model.applications[POSTGRESQL].remove_relation(
        f"{APP_NAME}:backend-db-admin", f"{POSTGRESQL}:db-admin"
    )
    with await ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[POSTGRESQL], status="active", timeout=1000),
            ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000),
        )
    cfg = await helpers.get_cfg(unit)
    # assert pgbouncer and postgres are completely disconnected.
    assert "pg_master" not in cfg["databases"].keys()
