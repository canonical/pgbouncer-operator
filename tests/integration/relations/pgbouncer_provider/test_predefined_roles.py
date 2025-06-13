#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os

import psycopg2
import psycopg2.sql
import pytest
from pytest_operator.plugin import OpsTest

from ... import markers
from ...helpers.helpers import (
    PG,
    PGB,
    get_juju_secret,
)
from ...helpers.postgresql_helpers import (
    get_password,
    get_unit_address,
)
from .helpers import (
    DATA_INTEGRATOR_APP_NAME,
    build_connection_string,
    db_connect,
    get_application_relation_data,
    get_primary,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15 * 60


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
@markers.pg16_only
async def test_deploy(ops_test: OpsTest, charm_noble):
    """Deploy the postgresql charm."""
    async with ops_test.fast_forward("10s"):
        await asyncio.gather(
            ops_test.model.deploy(
                charm_noble, application_name=PGB, num_units=0, base="ubuntu@24.04"
            ),
            ops_test.model.deploy(
                charm_noble, application_name=f"{PGB}2", num_units=0, base="ubuntu@24.04"
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
                config={"profile": "testing"},
            ),
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                channel="edge",
                base="ubuntu@24.04",
            ),
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                application_name=f"{DATA_INTEGRATOR_APP_NAME}2",
                channel="edge",
                base="ubuntu@24.04",
            ),
        )
        await ops_test.model.add_relation(PG, PGB)
        await ops_test.model.add_relation(PG, f"{PGB}2")

        await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=TIMEOUT)
        assert ops_test.model.applications[PG].units[0].workload_status == "active"

        await ops_test.model.wait_for_idle(
            apps=[DATA_INTEGRATOR_APP_NAME, f"{DATA_INTEGRATOR_APP_NAME}2"],
            status="blocked",
            timeout=(5 * 60),
        )


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_charmed_read_role(ops_test: OpsTest):
    """Test the charmed_read predefined role."""
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].set_config({
        "database-name": "charmed_read_database",
        "extra-user-roles": "charmed_read",
    })
    await ops_test.model.add_relation(DATA_INTEGRATOR_APP_NAME, PGB)
    await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    primary = await get_primary(ops_test, f"{PG}/0")
    primary_address = get_unit_address(ops_test, primary)
    operator_password = await get_password(ops_test, primary, "operator", use_secrets=True)

    with db_connect(
        primary_address, operator_password, username="operator", database="charmed_read_database"
    ) as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE test_table (id SERIAL PRIMARY KEY, data TEXT);")
            cursor.execute("INSERT INTO test_table (data) VALUES ('test_data'), ('test_data_2');")

    connection_string = await build_connection_string(
        ops_test,
        DATA_INTEGRATOR_APP_NAME,
        "postgresql",
        database="charmed_read_database",
        port=6432,
    )

    with psycopg2.connect(connection_string) as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            logger.info("Checking that the charmed_read role can read from the database")
            cursor.execute("RESET ROLE;")
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name NOT LIKE 'pg_%' AND table_name NOT LIKE 'sql_%' AND table_type <> 'VIEW';"
            )
            tables = [row[0] for row in cursor.fetchall()]
            assert tables == ["test_table"], "Unexpected tables in the database"

            cursor.execute("SELECT data FROM test_table;")
            data = sorted([row[0] for row in cursor.fetchall()])
            assert data == sorted(["test_data", "test_data_2"]), (
                "Unexpected data in charmed_read_database with charmed_read role"
            )
            logger.info("Checking that the charmed_read role cannot create a new table")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
    connection.close()

    with psycopg2.connect(connection_string) as connection, connection.cursor() as cursor:
        logger.info("Checking that the charmed_read role cannot write to an existing table")
        cursor.execute("RESET ROLE;")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute(
                "INSERT INTO test_table (data) VALUES ('test_data_3'), ('test_data_4');"
            )
    connection.close()

    await ops_test.model.applications[PG].remove_relation(
        f"{PGB}:database", f"{DATA_INTEGRATOR_APP_NAME}:postgresql"
    )
    await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked")


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_charmed_dml_role(ops_test: OpsTest):
    """Test the charmed_dml role."""
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].set_config({
        "database-name": "charmed_dml_database",
    })
    await ops_test.model.add_relation(DATA_INTEGRATOR_APP_NAME, PGB)
    await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    await ops_test.model.applications[f"{DATA_INTEGRATOR_APP_NAME}2"].set_config({
        "database-name": "throwaway",
        "extra-user-roles": "charmed_dml",
    })
    await ops_test.model.add_relation(f"{DATA_INTEGRATOR_APP_NAME}2", f"{PGB}2")
    await ops_test.model.wait_for_idle(
        apps=[f"{DATA_INTEGRATOR_APP_NAME}2", f"{PGB}2"], status="active"
    )

    connection_string = await build_connection_string(
        ops_test,
        DATA_INTEGRATOR_APP_NAME,
        "postgresql",
        database="charmed_dml_database",
        port=6432,
    )

    with psycopg2.connect(connection_string) as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE test_table (id SERIAL PRIMARY KEY, data TEXT);")

            cursor.execute("INSERT INTO test_table (data) VALUES ('test_data'), ('test_data_2');")

            cursor.execute("SELECT data FROM test_table;")
            data = sorted([row[0] for row in cursor.fetchall()])
            assert data == sorted(["test_data", "test_data_2"]), (
                "Unexpected data in charmed_dml_database with charmed_dml role"
            )

    primary = await get_primary(ops_test, f"{PG}/0")
    primary_address = get_unit_address(ops_test, primary)
    operator_password = await get_password(ops_test, primary, "operator", use_secrets=True)

    secret_uri = await get_application_relation_data(
        ops_test,
        f"{DATA_INTEGRATOR_APP_NAME}2",
        "postgresql",
        "secret-user",
    )
    secret_data = await get_juju_secret(ops_test, secret_uri)
    data_integrator_2_user = secret_data["username"]
    data_integrator_2_password = secret_data["password"]

    with db_connect(primary_address, operator_password, username="operator") as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute(
                psycopg2.sql.SQL("GRANT connect ON DATABASE charmed_dml_database TO {};").format(
                    psycopg2.sql.Identifier(data_integrator_2_user)
                )
            )

    with db_connect(
        primary_address,
        data_integrator_2_password,
        username=data_integrator_2_user,
        database="charmed_dml_database",
    ) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO test_table (data) VALUES ('test_data_3');")

    with db_connect(
        primary_address, operator_password, username="operator", database="charmed_dml_database"
    ) as connection:
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute("SELECT data FROM test_table;")
            data = sorted([row[0] for row in cursor.fetchall()])
            assert data == sorted(["test_data", "test_data_2", "test_data_3"]), (
                "Unexpected data in charmed_read_database with charmed_read role"
            )

    await ops_test.model.applications[PG].remove_relation(
        f"{PGB}:database", f"{DATA_INTEGRATOR_APP_NAME}:postgresql"
    )
    await ops_test.model.applications[PG].remove_relation(
        f"{PGB}2:database", f"{DATA_INTEGRATOR_APP_NAME}2:postgresql"
    )
    await ops_test.model.wait_for_idle(
        apps=[DATA_INTEGRATOR_APP_NAME, f"{DATA_INTEGRATOR_APP_NAME}2"], status="blocked"
    )
