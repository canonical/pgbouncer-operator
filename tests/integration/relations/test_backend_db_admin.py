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


@pytest.mark.abort_on_fail
@pytest.mark.legacy_relations
async def test_create_backend_db_admin_legacy_relation_slowtest(ops_test: OpsTest):
    """Test that the pgbouncer and postgres charms can relate to one another.

    This test is marked "slowtest", meaning it won't run when you run "tox -e fast-integration".
    This is because it's very slow.
    """
    # Build, deploy, and relate charms.
    pg = "postgresql"
    charm = await ops_test.build_charm(".")
    await asyncio.gather(
        ops_test.model.deploy(
            charm,
            application_name=APP_NAME,
        ),
        ops_test.model.deploy(pg),
    )
    # Pgbouncer enters a waiting state without backend postgres relation
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=1000)
    await ops_test.model.add_relation(f"{APP_NAME}:backend-db-admin", f"{pg}:db-admin")
    # Pgbouncer enters a waiting status without a postgres backend database relation
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)

    unit = ops_test.model.units["pgbouncer-operator/0"]
    cfg = await helpers.get_cfg(unit)
    # When there's only one postgres unit, we're in "standalone" mode with no standby replicas.
    assert list(cfg["databases"].keys()) == ["pg_master"]


@pytest.mark.legacy_relations
async def test_backend_db_admin_legacy_relation_scaling_slowtest(ops_test: OpsTest):
    """Test that the pgbouncer config accurately reflects postgres replication changes.

    Requires existing deployed pgbouncer and legacy postgres charms, connected by a
    backend-db-admin relation
    """
    pg = "postgresql"
    unit = ops_test.model.units["pgbouncer-operator/0"]
    await ops_test.model.applications[pg].add_units(count=2)
    await asyncio.gather(
        ops_test.model.wait_for_idle(
            apps=[pg], status="active", timeout=1000, wait_for_exact_units=3
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

    await ops_test.model.destroy_unit("postgresql/1")
    await asyncio.gather(
        ops_test.model.wait_for_idle(
            apps=[pg], status="active", timeout=1000, wait_for_exact_units=2
        ),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", timeout=1000, wait_for_exact_units=1
        ),
    )
    cfg = await helpers.get_cfg(unit)
    # Now there are two postgres units, and the config reflects this.
    assert list(cfg["databases"].keys()) == ["pg_master", "pgb_postgres_standby_0"]
    assert "pgb_postgres_standby_0" not in cfg["databases"].keys()

    await ops_test.model.destroy_unit("postgresql/1")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)
    cfg = await helpers.get_cfg(unit)
    # Now there is only one config, with no replicas, and the config reflects this.
    assert list(cfg["databases"].keys()) == ["pg_master"]
    assert "pgb_postgres_standby_0" not in cfg["databases"].keys()

    # Remove relation but keep pg application because we're going to need it for future tests.
    await ops_test.model.applications[pg].remove_relation(
        f"{APP_NAME}:backend-db-admin", f"{pg}:db-admin"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, pg], status="active", timeout=1000)
    cfg = await helpers.get_cfg(unit)
    # assert pgbouncer and postgres are completely disconnected.
    assert "pg_master" not in cfg["databases"].keys()
