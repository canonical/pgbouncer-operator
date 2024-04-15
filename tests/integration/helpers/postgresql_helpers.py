#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import itertools
import os
import subprocess
import tempfile
import zipfile
from typing import Dict, List, Optional

import psycopg2
import yaml
from juju.unit import Unit
from pytest_operator.plugin import OpsTest

from .helpers import PG, PGB


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
        (
            "SELECT CONCAT(usename, ':', usesuper) FROM pg_catalog.pg_user;"
            if admin
            else "SELECT usename FROM pg_catalog.pg_user;"
        ),
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
        user: The user to execute as.
        password: The PostgreSQL user password.
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


async def get_postgres_primary(ops_test: OpsTest) -> str:
    """Get the PostgreSQL primary unit.

    Args:
        ops_test: ops_test instance.

    Returns:
        the current PostgreSQL primary unit.
    """
    action = await ops_test.model.units.get(f"{PG}/0").run_action("get-primary")
    action = await action.wait()
    return action.results["primary"]


def get_unit_address(ops_test: OpsTest, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    return ops_test.model.units.get(unit_name).public_address


async def run_command_on_unit(ops_test: OpsTest, unit_name: str, command: str) -> str:
    """Run a command on a specific unit.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit to run the command on
        command: The command to run

    Returns:
        the command output if it succeeds, otherwise raises an exception.
    """
    complete_command = ["exec", "--unit", unit_name, "--", *command.split()]
    return_code, stdout, _ = await ops_test.juju(*complete_command)
    if return_code != 0:
        raise Exception(
            "Expected command %s to succeed instead it failed: %s", command, return_code
        )
    return stdout


async def get_machine_from_unit(ops_test: OpsTest, unit_name: str) -> str:
    """Get the name of the machine from a specific unit.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit to get the machine

    Returns:
        The name of the machine.
    """
    raw_hostname = await run_command_on_unit(ops_test, unit_name, "hostname")
    return raw_hostname.strip()


async def restart_machine(ops_test: OpsTest, unit_name: str) -> None:
    """Restart the machine where a unit run on.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit to restart the machine
    """
    raw_hostname = await get_machine_from_unit(ops_test, unit_name)
    restart_machine_command = f"lxc restart {raw_hostname}"
    subprocess.check_call(restart_machine_command.split())


async def get_leader_unit(ops_test: OpsTest, app: str) -> Optional[Unit]:
    leader_unit = None
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
            break

    return leader_unit


async def deploy_and_relate_bundle_with_pgbouncer(
    ops_test: OpsTest,
    bundle_name: str,
    main_application_name: str,
    main_application_num_units: int = None,
    relation_name: str = "db",
    status: str = "active",
    status_message: str = None,
    overlay: Dict = None,
    timeout: int = 2000,
) -> str:
    """Helper function to deploy and relate a bundle with PostgreSQL.

    Args:
        ops_test: The ops test framework.
        bundle_name: The name of the bundle to deploy.
        main_application_name: The name of the application that should be
            related to PostgreSQL.
        main_application_num_units: Optional number of units for the main
            application.
        relation_name: The name of the relation to use in PostgreSQL
            (db or db-admin).
        status: Status to wait for in the application after relating
            it to PostgreSQL.
        status_message: Status message to wait for in the application after
            relating it to PostgreSQL.
        overlay: Optional overlay to be used when deploying the bundle.
        timeout: Timeout to wait for the deployment to idle.
    """
    # Deploy the bundle.
    with tempfile.NamedTemporaryFile(dir=os.getcwd()) as original:
        # Download the original bundle.
        await ops_test.juju("download", bundle_name, "--filepath", original.name)

        # Open the bundle compressed file and update the contents
        # of the bundle.yaml file to deploy it.
        with zipfile.ZipFile(original.name, "r") as archive:
            bundle_yaml = archive.read("bundle.yaml")
            data = yaml.load(bundle_yaml, Loader=yaml.FullLoader)

            if main_application_num_units is not None:
                data["applications"][main_application_name]["num_units"] = (
                    main_application_num_units
                )

            # Save the list of relations other than `db` and `db-admin`,
            # so we can add them back later.
            other_relations = [
                relation for relation in data["relations"] if "postgresql" in relation
            ]

            # Remove PostgreSQL and relations with it from the bundle.yaml file.
            del data["applications"]["postgresql"]
            data["relations"] = [
                relation
                for relation in data["relations"]
                if "postgresql" not in relation
                and "postgresql:db" not in relation
                and "postgresql:db-admin" not in relation
            ]

            # Write the new bundle content to a temporary file and deploy it.
            with tempfile.NamedTemporaryFile(dir=os.getcwd()) as patched:
                patched.write(yaml.dump(data).encode("utf_8"))
                patched.seek(0)
                if overlay is not None:
                    with tempfile.NamedTemporaryFile() as overlay_file:
                        overlay_file.write(yaml.dump(overlay).encode("utf_8"))
                        overlay_file.seek(0)
                        await ops_test.juju("deploy", patched.name, "--overlay", overlay_file.name)
                else:
                    await ops_test.juju("deploy", patched.name)

    async with ops_test.fast_forward(fast_interval="30s"):
        # Relate application to PostgreSQL.
        relation = await ops_test.model.relate(main_application_name, f"{PGB}:{relation_name}")

        # Restore previous existing relations.
        for other_relation in other_relations:
            await ops_test.model.relate(other_relation[0], other_relation[1])

        # Wait for the deployment to complete.
        unit = ops_test.model.units.get(f"{main_application_name}/0")
        awaits = [
            ops_test.model.wait_for_idle(
                apps=[PG, PGB],
                status="active",
                timeout=timeout,
            ),
            ops_test.model.wait_for_idle(
                apps=[main_application_name],
                raise_on_blocked=False,
                status=status,
                timeout=timeout,
            ),
        ]
        if status_message:
            awaits.append(
                ops_test.model.block_until(
                    lambda: unit.workload_status_message == status_message, timeout=timeout
                )
            )
        await asyncio.gather(*awaits)

    return relation.id


async def get_password(ops_test: OpsTest, unit_name: str, username: str = "operator") -> str:
    """Retrieve a user password using the action.

    Args:
        ops_test: ops_test instance.
        unit_name: the name of the unit.
        username: the user to get the password.

    Returns:
        the user password.
    """
    unit = ops_test.model.units.get(unit_name)
    action = await unit.run_action("get-password", **{"username": username})
    result = await action.wait()
    return result.results["password"]


async def get_landscape_api_credentials(ops_test: OpsTest) -> List[str]:
    """Returns the key and secret to be used in the Landscape API.

    Args:
        ops_test: The ops test framework
    """
    unit = ops_test.model.applications[PG].units[0]
    password = await get_password(ops_test, unit.name)
    unit_address = await unit.get_public_address()

    output = await execute_query_on_unit(
        unit_address,
        password,
        "SELECT encode(access_key_id,'escape'), encode(access_secret_key,'escape') FROM api_credentials;",
        database="landscape-standalone-main",
    )

    return output
