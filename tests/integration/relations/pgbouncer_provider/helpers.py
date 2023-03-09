#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
import logging
from typing import Optional
from uuid import uuid4

import yaml
from pytest_operator.plugin import OpsTest


async def get_application_relation_data(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    key: str,
    relation_id: str = None,
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


async def run_sql_on_application_charm(
    ops_test,
    unit_name: str,
    query: str,
    dbname: str,
    relation_id,
    readonly: bool = False,
    timeout=30,
):
    """Runs the given sql query on the given application charm."""
    client_unit = ops_test.model.units.get(unit_name)
    params = {"dbname": dbname, "query": query, "relation-id": relation_id, "readonly": readonly}
    logging.info(f"running query: \n {query}")
    action = await client_unit.run_action("run-sql", **params)
    result = await asyncio.wait_for(action.wait(), timeout)
    logging.info(f"query results: {result.results}")
    return result.results


async def build_connection_string(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    *,
    relation_id: str = None,
    read_only_endpoint: bool = False,
) -> str:
    """Build a PostgreSQL connection string.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        relation_id: id of the relation to get connection data from
        read_only_endpoint: whether to choose the read-only endpoint
            instead of the read/write endpoint

    Returns:
        a PostgreSQL connection string
    """
    # Get the connection data exposed to the application through the relation.
    database = f'{application_name.replace("-", "_")}_{relation_name.replace("-", "_")}'
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
    return f"dbname='{database}' user='{username}' host='{host}' password='{password}' connect_timeout=10"


async def check_new_relation(ops_test: OpsTest, unit_name, relation_id, dbname):
    """Smoke test to check relation is online."""
    table_name = "quick_test"
    smoke_val = str(uuid4())

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
        relation_id=relation_id,
    )
    assert smoke_val in json.loads(run_update_query["results"])[0]
