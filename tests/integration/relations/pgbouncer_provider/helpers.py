#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
import logging
from typing import Dict, Optional
from uuid import uuid4

import psycopg2
import pytest
import yaml
from juju.unit import Unit
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, stop_after_delay, wait_fixed

from ...helpers.helpers import get_juju_secret

DATA_INTEGRATOR_APP_NAME = "data-integrator"


logger = logging.getLogger(__name__)


def check_connected_user(
    cursor, session_user: str, current_user: str, primary: bool = True
) -> None:
    cursor.execute("SELECT session_user,current_user;")
    result = cursor.fetchone()
    if result is not None:
        instance = "primary" if primary else "replica"
        assert result[0] == session_user, (
            f"The session user should be the {session_user} user in the {instance}"
        )
        assert result[1] == current_user, (
            f"The current user should be the {current_user} user in the {instance}"
        )
    else:
        assert False, "No result returned from the query"


async def check_roles_and_their_permissions(
    ops_test: OpsTest, relation_endpoint: str, database_name: str
) -> None:
    action = await ops_test.model.units[f"{DATA_INTEGRATOR_APP_NAME}/0"].run_action(
        action_name="get-credentials"
    )
    result = await action.wait()
    data_integrator_credentials = result.results
    username = data_integrator_credentials[relation_endpoint]["username"]
    uris = data_integrator_credentials[relation_endpoint]["uris"]
    connection = None
    try:
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                connection = psycopg2.connect(uris)
        connection.autocommit = True
        with connection.cursor() as cursor:
            logger.info(
                "Checking that the relation user is automatically escalated to the database owner user"
            )
            check_connected_user(cursor, username, f"{database_name}_owner")
            logger.info("Creating a test table and inserting data")
            cursor.execute("CREATE TABLE test_table (id INTEGER);")
            logger.info("Inserting data into the test table")
            cursor.execute("INSERT INTO test_table(id) VALUES(1);")
            logger.info("Reading data from the test table")
            cursor.execute("SELECT * FROM test_table;")
            result = cursor.fetchall()
            assert len(result) == 1, "The database owner user should be able to read the data"

            logger.info("Checking that the database owner user can't create a database")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute(f"CREATE DATABASE {database_name}_2;")

            logger.info("Checking that the relation user can't create a table")
            cursor.execute("RESET ROLE;")
            check_connected_user(cursor, username, username)
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE test_table_2 (id INTEGER);")
    finally:
        if connection is not None:
            connection.close()

    connection_string = f"host={data_integrator_credentials[relation_endpoint]['read-only-endpoints'].split(':')[0]} port=6432 dbname={data_integrator_credentials[relation_endpoint]['database']}_readonly user={username} password={data_integrator_credentials[relation_endpoint]['password']}"
    connection = None
    try:
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                connection = psycopg2.connect(connection_string)
        with connection.cursor() as cursor:
            logger.info("Checking that the relation user can read data from the database")
            check_connected_user(cursor, username, username, primary=False)
            logger.info("Reading data from the test table")
            cursor.execute("SELECT * FROM test_table;")
            result = cursor.fetchall()
            assert len(result) == 1, "The relation user should be able to read the data"
    finally:
        if connection is not None:
            connection.close()


async def get_application_relation_data(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    key: str,
    relation_id: Optional[str] = None,
) -> Optional[str]:
    """Get relation data for an application.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        key: key of data to be retrieved
        relation_id: id of the relation to get connection data from

    Returns:
        the relation data that was requested, or None if no data in the relation

    Raises:
        ValueError if it's not possible to get application unit data
            or if there is no data for the particular relation endpoint.
    """
    unit_name = ops_test.model.applications[application_name].units[0].name
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]
    if relation_id:
        # Filter the data based on the relation id.
        relation_data = [v for v in relation_data if v["relation-id"] == relation_id]
    if len(relation_data) == 0:
        raise ValueError(
            f"no relation data could be grabbed on relation with endpoint {relation_name}"
        )
    return relation_data[0]["application-data"].get(key)


def relations(ops_test: OpsTest, provider_app: str, requirer_app: str) -> list:
    return [
        relation
        for relation in ops_test.model.applications[provider_app].relations
        if not relation.is_peer and relation.requires.application_name == requirer_app
    ]


async def run_sql_on_application_charm(
    ops_test,
    unit_name: str,
    query: str,
    dbname: str,
    relation_name,
    readonly: bool = False,
    timeout=30,
):
    """Runs the given sql query on the given application charm."""
    client_unit = ops_test.model.units.get(unit_name)
    params = {
        "dbname": dbname,
        "query": query,
        "relation-name": relation_name,
        "readonly": readonly,
    }
    logging.info(f"running query: \n {query}")
    logging.info(params)
    action = await client_unit.run_action("run-sql", **params)
    result = await asyncio.wait_for(action.wait(), timeout)
    logging.info(f"query results: {result.results}")
    return result.results


async def build_connection_string(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    *,
    relation_id: Optional[str] = None,
    read_only_endpoint: bool = False,
    database: Optional[str] = None,
    port: int = 5432,
) -> str:
    """Build a PostgreSQL connection string.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        relation_id: id of the relation to get connection data from
        read_only_endpoint: whether to choose the read-only endpoint
            instead of the read/write endpoint
        database: optional database to be used in the connection string
        port: optional port to connect to.

    Returns:
        a PostgreSQL connection string
    """
    # Get the connection data exposed to the application through the relation.
    if database is None:
        database = f"{application_name.replace('-', '_')}_{relation_name.replace('-', '_')}"

    if secret_uri := await get_application_relation_data(
        ops_test,
        application_name,
        relation_name,
        "secret-user",
        relation_id,
    ):
        secret_data = await get_juju_secret(ops_test, secret_uri)
        username = secret_data["username"]
        password = secret_data["password"]
    else:
        username = await get_application_relation_data(
            ops_test, application_name, relation_name, "username", relation_id
        )
        password = await get_application_relation_data(
            ops_test, application_name, relation_name, "password", relation_id
        )
    endpoints = await get_application_relation_data(
        ops_test,
        application_name,
        relation_name,
        "read-only-endpoints" if read_only_endpoint else "endpoints",
        relation_id,
    )
    host = endpoints.split(",")[0].split(":")[0]

    # Build the complete connection string to connect to the database.
    return f"dbname='{database}' user='{username}' host='{host}' port={port} password='{password}' connect_timeout=10"


async def check_new_relation(ops_test: OpsTest, unit_name, relation_name, dbname):
    """Smoke test to check relation is online."""
    table_name = "quick_test"
    smoke_val = str(uuid4())

    # TODO Fails frequently. Investigate and stabilise.
    for attempt in Retrying(stop=stop_after_attempt(5), wait=wait_fixed(1), reraise=True):
        with attempt:
            smoke_query = (
                # TODO fix ownership of DB objects on rerelation in PG to be able to drop
                f"CREATE TABLE IF NOT EXISTS {table_name}(data TEXT);"
                f"INSERT INTO {table_name}(data) VALUES('{smoke_val}');"
                f"SELECT data FROM {table_name} WHERE data = '{smoke_val}';"
            )
            run_update_query = await run_sql_on_application_charm(
                ops_test,
                unit_name=unit_name,
                query=smoke_query,
                dbname=dbname,
                relation_name=relation_name,
            )
            assert smoke_val in json.loads(run_update_query["results"])[0]


async def fetch_action_get_credentials(unit: Unit) -> Dict:
    """Helper to run an action to fetch connection info.

    Args:
        unit: The juju unit on which to run the get_credentials action for credentials
    Returns:
        A dictionary with the username, password and access info for the service
    """
    action = await unit.run_action(action_name="get-credentials")
    result = await action.wait()
    return result.results


def check_exposed_connection(credentials, tls):
    table_name = "expose_test"
    smoke_val = str(uuid4())

    sslmode = "require" if tls else "disable"
    if "uris" in credentials["postgresql"]:
        uri = credentials["postgresql"]["uris"]
        connstr = f"{uri}?connect_timeout=1&sslmode={sslmode}"
    else:
        host, port = credentials["postgresql"]["endpoints"].split(":")
        user = credentials["postgresql"]["username"]
        password = credentials["postgresql"]["password"]
        database = credentials["postgresql"]["database"]
        connstr = f"dbname='{database}' user='{user}' host='{host}' port='{port}' password='{password}' connect_timeout=1 sslmode={sslmode}"
    connection = psycopg2.connect(connstr)
    connection.autocommit = True
    smoke_query = (
        f"DROP TABLE IF EXISTS {table_name};"
        f"CREATE TABLE {table_name}(data TEXT);"
        f"INSERT INTO {table_name}(data) VALUES('{smoke_val}');"
        f"SELECT data FROM {table_name} WHERE data = '{smoke_val}';"
    )
    cursor = connection.cursor()
    cursor.execute(smoke_query)

    assert smoke_val == cursor.fetchone()[0]


def db_connect(
    host: str, password: str, username: str = "operator", database: str = "postgres"
) -> psycopg2.extensions.connection:
    """Returns psycopg2 connection object linked to postgres db in the given host.

    Args:
        host: the IP of the postgres host
        password: user password
        username: username to connect with
        database: database to connect to

    Returns:
        psycopg2 connection object linked to postgres db, under "operator" user.
    """
    return psycopg2.connect(
        f"dbname='{database}' user='{username}' host='{host}' password='{password}' connect_timeout=10"
    )


async def get_primary(ops_test: OpsTest, unit_name: str, model=None) -> str:
    """Get the primary unit.

    Args:
        ops_test: ops_test instance.
        unit_name: the name of the unit.
        model: Model to use.

    Returns:
        the current primary unit.
    """
    if not model:
        model = ops_test.model
    action = await model.units.get(unit_name).run_action("get-primary")
    action = await action.wait()
    if "primary" not in action.results or action.results["primary"] not in model.units:
        raise Exception("Primary unit not found")
    return action.results["primary"]
