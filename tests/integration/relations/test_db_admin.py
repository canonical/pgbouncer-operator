#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

from tests.integration.helpers.helpers import (
    deploy_postgres_bundle,
    get_app_relation_databag,
    run_sql,
    wait_for_relation_joined_between,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"
PSQL = "psql"
RELATION = "db-admin"


@pytest.mark.legacy_relation
async def test_db_admin_with_psql(ops_test: OpsTest) -> None:
    # Deploy application.
    await ops_test.model.deploy(
        "postgresql-charmers-postgresql-client",
        application_name=PSQL,
    )
    await deploy_postgres_bundle(ops_test, db_units=1)

    psql_relation = await ops_test.model.relate(f"{PSQL}:db", f"{PGB}:{RELATION}")
    wait_for_relation_joined_between(ops_test, PGB, PSQL)
    await ops_test.model.wait_for_idle(
        apps=[PSQL, PG, PGB],
        status="active",
        timeout=600,
    )

    unit_name = f"{PSQL}/0"
    psql_databag = await get_app_relation_databag(ops_test, unit_name, psql_relation.id)

    pgpass = psql_databag.get("password")
    user = psql_databag.get("user")
    host = psql_databag.get("host")
    port = psql_databag.get("port")
    dbname = psql_databag.get("database")

    assert None not in [pgpass, user, host, port, dbname], "databag incorrectly populated"

    user_command = "CREATE ROLE myuser3 LOGIN PASSWORD 'mypass';"
    rtn, _, err = await run_sql(
        ops_test, unit_name, user_command, pgpass, user, host, port, dbname
    )
    assert rtn == 0, f"failed to run admin command {user_command}, {err}"

    db_command = "CREATE DATABASE test_db;"
    rtn, _, err = await run_sql(ops_test, unit_name, db_command, pgpass, user, host, port, dbname)
    assert rtn == 0, f"failed to run admin command {db_command}, {err}"
