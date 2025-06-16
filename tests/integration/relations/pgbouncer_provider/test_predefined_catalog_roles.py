#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os

import psycopg2 as psycopg2
import pytest as pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from ... import markers
from ...helpers.helpers import (
    PG,
    PGB,
)
from ...helpers.postgresql_helpers import (
    get_password,
    get_unit_address,
)
from .helpers import (
    DATA_INTEGRATOR_APP_NAME,
    build_connection_string,
    check_connected_user,
    check_roles_and_their_permissions,
    db_connect,
    get_primary,
    relations,
)

logger = logging.getLogger(__name__)

DATABASE_NAME = "test"
RELATION_ENDPOINT = "postgresql"
TIMEOUT = 15 * 60


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_deploy(ops_test: OpsTest, charm_noble) -> None:
    """Deploy and relate the charms."""
    reset_relation = False
    if PGB not in ops_test.model.applications:
        logger.info("Deploying PgBouncer charm")
        await ops_test.model.deploy(
            charm_noble, application_name=PGB, num_units=0, base="ubuntu@24.04"
        )
    if PG not in ops_test.model.applications:
        logger.info("Deploying database charm")
        await ops_test.model.deploy(
            PG,
            channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
            config={"profile": "testing"},
            num_units=2,
            base="ubuntu@24.04",
        )
    else:
        logger.info("Dropping test databases from already deployed database charm")
        primary = await get_primary(ops_test, f"{PG}/0")
        connection = None
        try:
            host = get_unit_address(ops_test, primary)
            password = await get_password(ops_test, f"{PG}/0", use_secrets=True)
            connection = db_connect(host, password)
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DATABASE_NAME}' AND leader_pid IS NULL;"
                )
                cursor.execute(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DATABASE_NAME}_2' AND leader_pid IS NULL;"
                )
                cursor.execute(f"DROP DATABASE IF EXISTS {DATABASE_NAME};")
                cursor.execute(f"DROP DATABASE IF EXISTS {DATABASE_NAME}_2;")
        finally:
            if connection is not None:
                connection.close()
        reset_relation = True
    if not relations(ops_test, PG, PGB):
        logger.info("Adding relation between PgBouncer and database charms")
        await ops_test.model.relate(PG, PGB)
    if DATA_INTEGRATOR_APP_NAME not in ops_test.model.applications:
        logger.info("Deploying data integrator charm")
        await ops_test.model.deploy(
            DATA_INTEGRATOR_APP_NAME,
            channel="edge",
            config={"database-name": DATABASE_NAME},
            base="ubuntu@24.04",
        )
    else:
        logger.info("Resetting extra user roles in already deployed data integrator charm")
        await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].set_config({
            "extra-user-roles": ""
        })
        reset_relation = True
    existing_relations = relations(ops_test, PGB, DATA_INTEGRATOR_APP_NAME)
    if reset_relation and existing_relations:
        logger.info("Removing existing relation between charms")
        await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].remove_relation(
            f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB
        )
        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked")
        logger.info("Adding relation between charms")
        await ops_test.model.relate(DATA_INTEGRATOR_APP_NAME, PGB)
    if not existing_relations:
        logger.info("Adding relation between charms")
        await ops_test.model.relate(DATA_INTEGRATOR_APP_NAME, PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[DATA_INTEGRATOR_APP_NAME, PGB, PG], status="active", timeout=TIMEOUT
        )


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_permissions(ops_test: OpsTest) -> None:
    """Test that the relation user is automatically escalated to the database owner user."""
    await check_roles_and_their_permissions(ops_test, RELATION_ENDPOINT, DATABASE_NAME)


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_remove_and_reestablish_relation(ops_test: OpsTest) -> None:
    """Test that the relation can be removed and re-added without issues."""
    logger.info("Removing existing relation between charms")
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].remove_relation(
        f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB
    )
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked"),
            ops_test.model.block_until(
                lambda: len(relations(ops_test, PGB, DATA_INTEGRATOR_APP_NAME)) == 0
            ),
        )

    logger.info("Dropping test table to recreate it")
    primary = await get_primary(ops_test, f"{PG}/0")
    connection = None
    try:
        host = get_unit_address(ops_test, primary)
        password = await get_password(ops_test, f"{PG}/0", use_secrets=True)
        connection = db_connect(host, password, database=DATABASE_NAME)
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE test_table;")
    finally:
        if connection is not None:
            connection.close()

    logger.info("Adding relation between charms")
    await ops_test.model.relate(DATA_INTEGRATOR_APP_NAME, PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    await check_roles_and_their_permissions(ops_test, RELATION_ENDPOINT, DATABASE_NAME)

    logger.info("Removing existing relation between charms")
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].remove_relation(
        f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB
    )
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked"),
            ops_test.model.block_until(
                lambda: len(relations(ops_test, PGB, DATA_INTEGRATOR_APP_NAME)) == 0
            ),
        )

    logger.info("Dropping test database to recreate it")
    primary = await get_primary(ops_test, f"{PG}/0")
    connection = None
    try:
        host = get_unit_address(ops_test, primary)
        password = await get_password(ops_test, f"{PG}/0", use_secrets=True)
        connection = db_connect(host, password)
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{DATABASE_NAME}' AND leader_pid IS NULL;"
            )
            cursor.execute(f"DROP DATABASE {DATABASE_NAME};")
    finally:
        if connection is not None:
            connection.close()

    logger.info("Adding relation between charms")
    await ops_test.model.relate(DATA_INTEGRATOR_APP_NAME, PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    await check_roles_and_their_permissions(ops_test, RELATION_ENDPOINT, DATABASE_NAME)


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_database_creation_permissions(ops_test: OpsTest) -> None:
    """Test that the database creation permissions are correctly set for the extra user role."""
    logger.info("Removing existing relation between charms")
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].remove_relation(
        f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB
    )
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME], status="blocked"),
            ops_test.model.block_until(
                lambda: len(relations(ops_test, PGB, DATA_INTEGRATOR_APP_NAME)) == 0
            ),
        )

    logger.info("Configuring data integrator charm for database creation extra user role")
    await ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].set_config({
        "extra-user-roles": "charmed_databases_owner"
    })

    logger.info("Adding relation between charms")
    await ops_test.model.relate(DATA_INTEGRATOR_APP_NAME, PGB)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[DATA_INTEGRATOR_APP_NAME, PGB], status="active")

    action = await ops_test.model.units[f"{DATA_INTEGRATOR_APP_NAME}/0"].run_action(
        action_name="get-credentials"
    )
    result = await action.wait()
    data_integrator_credentials = result.results
    username = data_integrator_credentials[RELATION_ENDPOINT]["username"]
    uris = data_integrator_credentials[RELATION_ENDPOINT]["uris"]
    connection = None
    try:
        connection = psycopg2.connect(uris)
        connection.autocommit = True
        with connection.cursor() as cursor:
            logger.info("Checking that the charmed_databases_owner user can create a database")
            check_connected_user(cursor, username, "charmed_databases_owner")
            cursor.execute(f"CREATE DATABASE {DATABASE_NAME}_2;")
            logger.info("Checking that the charmed_databases_owner user can't create a table")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
            logger.info(
                "Checking that the relation user can escalate to the database owner user and create a table"
            )
            cursor.execute("RESET ROLE;")
            cursor.execute(f"SET ROLE {DATABASE_NAME}_owner;")
            check_connected_user(cursor, username, f"{DATABASE_NAME}_owner")
            cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
            logger.info(
                "Checking that the relation user can escalate to the charmed_databases_owner user again"
            )
            cursor.execute("RESET ROLE;")
            cursor.execute("SET ROLE charmed_databases_owner;")
            check_connected_user(cursor, username, "charmed_databases_owner")
    finally:
        if connection is not None:
            connection.close()


@pytest.mark.abort_on_fail
@markers.pg16_only
async def test_newly_created_database_permissions(ops_test: OpsTest) -> None:
    """Test that the newly created database has the correct permissions."""
    action = await ops_test.model.units[f"{DATA_INTEGRATOR_APP_NAME}/0"].run_action(
        action_name="get-credentials"
    )
    result = await action.wait()
    data_integrator_credentials = result.results
    username = data_integrator_credentials[RELATION_ENDPOINT]["username"]
    connection_string = await build_connection_string(
        ops_test,
        DATA_INTEGRATOR_APP_NAME,
        "postgresql",
        database=f"{DATABASE_NAME}_2",
        port=6432,
    )
    connection = None
    for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3), reraise=True):
        with attempt:
            connection = psycopg2.connect(connection_string)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            logger.info("Checking that the charmed_databases_owner user can create a table")
            check_connected_user(cursor, username, "charmed_databases_owner")
            cursor.execute("DROP TABLE IF EXISTS test_table;")
            cursor.execute("CREATE TABLE test_table (id INTEGER);")
            logger.info(
                "Checking that the charmed_databases_owner user can't create a table anymore after executing the set_up_predefined_catalog_roles() function"
            )
            cursor.execute("SELECT set_up_predefined_catalog_roles();")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
            logger.info(
                "Checking that the relation user can escalate to the database owner user and create a table"
            )
            cursor.execute("RESET ROLE;")
            cursor.execute(f"SET ROLE {DATABASE_NAME}_2_owner;")
            check_connected_user(cursor, username, f"{DATABASE_NAME}_2_owner")
            cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
    finally:
        if connection is not None:
            connection.close()
