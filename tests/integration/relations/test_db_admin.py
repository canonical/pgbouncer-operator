#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers.helpers import (
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_legacy_relation_username,
    wait_for_relation_joined_between,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"
TELEGRAF = "telegraf"
INFLUXDB = "influxdb"


@pytest.mark.legacy_relation
async def test_db_admin_with_telegraf(ops_test: OpsTest) -> None:
    """Deploy telegraf and influxdb to test the 'db-admin' relation."""
    backend_relation = await deploy_postgres_bundle(ops_test, db_units=1)
    async with ops_test.fast_forward():
        # Deploy Telegraf
        telegraf_relation = await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test, TELEGRAF, relation="db-admin"
        )

        await asyncio.gather(
            ops_test.model.relate(TELEGRAF, f"{PGB}:juju-info"),
            ops_test.model.deploy(INFLUXDB),
        )

        await ops_test.model.relate(TELEGRAF, INFLUXDB)
        wait_for_relation_joined_between(ops_test, PGB, TELEGRAF)
        wait_for_relation_joined_between(ops_test, INFLUXDB, TELEGRAF)

        await ops_test.model.wait_for_idle(
            apps=[TELEGRAF, INFLUXDB, PG, PGB],
            status="active",
            timeout=1000,
        )

        pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)
        await check_databases_creation(ops_test, ["mailman3"], pgb_user, pgb_pass)

        telegraf_users = get_legacy_relation_username(ops_test, telegraf_relation.id)

        await check_database_users_existence(ops_test, [telegraf_users], [], pgb_user, pgb_pass)

        # TODO assert telegraf is working
