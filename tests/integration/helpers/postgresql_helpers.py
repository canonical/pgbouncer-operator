#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import itertools
from pathlib import Path
from typing import List

import psycopg2
import yaml
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PG = "postgresql"

async def build_connection_string(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    read_only_endpoint: bool = False,
) -> str:
    """Returns a PostgreSQL connection string.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        read_only_endpoint: whether to choose the read-only endpoint
            instead of the read/write endpoint

    Returns:
        a PostgreSQL connection string
    """
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]
    if len(relation_data) == 0:
        raise ValueError(
            f"no relation data could be grabbed on relation with endpoint {relation_name}"
        )
    data = relation_data[0]["application-data"]
    if read_only_endpoint:
        return data.get("standbys").split(",")[0]
    else:
        return data.get("master")


async def check_database_users_existence(
    ops_test: OpsTest,
    users_that_should_exist: List[str],
    users_that_should_not_exist: List[str],
    pg_user: str,
    pg_user_password: str,
    admin: bool = False,
) -> None:
    """Checks that applications users exist in the database.

    Args:
        ops_test: The ops test framework
        users_that_should_exist: List of users that should exist in the database
        users_that_should_not_exist: List of users that should not exist in the database
        admin: Whether to check if the existing users are superusers
        pg_user: an admin user that can access the database
        pg_user_password: password for `pg_user`
    """
    unit = ops_test.model.applications[PG].units[0]
    unit_address = get_unit_address(ops_test, unit.name)

    # Retrieve all users in the database.
    output = await execute_query_on_unit(
        unit_address,
        pg_user,
        pg_user_password,
        "SELECT CONCAT(usename, ':', usesuper) FROM pg_catalog.pg_user;"
        if admin
        else "SELECT usename FROM pg_catalog.pg_user;",
    )
    # Assert users that should exist.
    for user in users_that_should_exist:
        if admin:
            # The t flag indicates the user is a superuser.
            assert f"{user}:t" in output
        else:
            assert user in output

    # Assert users that should not exist.
    for user in users_that_should_not_exist:
        assert user not in output


async def check_databases_creation(
    ops_test: OpsTest, databases: List[str], user: str, password: str
) -> None:
    """Checks that database and tables are successfully created for the application.

    Args:
        ops_test: The ops test framework
        databases: List of database names that should have been created
        user: an admin user that can access the database
        password: password for `user`
    """
    unit = ops_test.model.applications[PG].units[0]

    for unit in ops_test.model.applications[PG].units:
        unit_address = await unit.get_public_address()

        for database in databases:
            # Ensure database exists in PostgreSQL.
            output = await execute_query_on_unit(
                unit_address,
                user,
                password,
                "SELECT datname FROM pg_database;",
            )
            assert database in output

            # Ensure that application tables exist in the database
            output = await execute_query_on_unit(
                unit_address,
                user,
                password,
                "SELECT table_name FROM information_schema.tables;",
                database=database,
            )
            assert len(output)


async def execute_query_on_unit(
    unit_address: str,
    user: str,
    password: str,
    query: str,
    database: str = "postgres",
):
    """Execute given PostgreSQL query on a unit.

    Args:
        unit_address: The public IP address of the unit to execute the query on.
        password: The PostgreSQL superuser password.
        query: Query to execute.
        database: Optional database to connect to (defaults to postgres database).

    Returns:
        A list of rows that were potentially returned from the query.
    """
    with psycopg2.connect(
        f"dbname='{database}' user='{user}' host='{unit_address}' password='{password}' connect_timeout=10"
    ) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        output = list(itertools.chain(*cursor.fetchall()))
    return output


def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    return ops_test.model.units.get(unit_name).public_address
