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
    get_app_relation_databag,
    get_backend_user_pass,
    get_legacy_relation_username,
    get_unit_info,
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
PSQL = "psql"

@pytest.mark.dev
@pytest.mark.legacy_relation
async def test_db_admin_with_psql(ops_test: OpsTest) -> None:
    pg_relation = await deploy_postgres_bundle(ops_test)
    psql_relation = await deploy_and_relate_application_with_pgbouncer_bundle(
        ops_test, "postgresql-charmers-postgresql-client", application_name=PSQL
    )
    unit_name = f"{PSQL}/0"
    psql_databag = get_app_relation_databag(ops_test, unit_name, psql_relation.id)

    pgpass = psql_databag.get("password")
    user = psql_databag.get("user")
    host = psql_databag.get("host")
    port = psql_databag.get("port")
    dbname = psql_databag.get("database")

    assert None in [pgpass,user,host,port,dbname], "databag incorrectly populated"

    user_command = f"run --unit {unit_name} -- PGPASSWORD={pgpass} psql --username={user} -h {host} -p {port} --dbname={dbname} --command=\"CREATE ROLE myuser3 LOGIN PASSWORD 'mypass' ;\""
    rtn, _, err = await ops_test.juju(*user_command.split(" "))
    assert rtn == 0, f"failed to run admin command, {err}"

    db_command = f"run --unit {unit_name} -- PGPASSWORD={pgpass} psql --username={user} -h {host} -p {port} --dbname={dbname} --command=\"CREATE DATABASE test_db;\""
    rtn, _, err = await ops_test.juju(*db_command.split(" "))
    assert rtn == 0, f"failed to run admin command, {err}"
