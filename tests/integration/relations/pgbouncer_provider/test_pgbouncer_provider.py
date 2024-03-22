#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
import logging

import pytest
from juju.errors import JujuAPIError
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME, PEER_RELATION_NAME
from tests.integration.helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
    SECOND_DATABASE_RELATION_NAME,
    get_app_relation_databag,
    get_backend_relation,
    get_backend_user_pass,
    scale_application,
)
from tests.integration.helpers.postgresql_helpers import check_database_users_existence
from tests.integration.relations.pgbouncer_provider.helpers import (
    build_connection_string,
    check_new_relation,
    get_application_relation_data,
    run_sql_on_application_charm,
)

logger = logging.getLogger(__name__)

DATA_INTEGRATOR_APP_NAME = "data-integrator"
CLIENT_UNIT_NAME = f"{CLIENT_APP_NAME}/0"
TEST_DBNAME = "postgresql_test_app_first_database"
ANOTHER_APPLICATION_APP_NAME = "another-application"
PG_2 = "another-postgresql"
PGB_2 = "another-pgbouncer"
APP_NAMES = [CLIENT_APP_NAME, PG]
MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME = "multiple-database-clusters"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_database_relation_with_charm_libraries(ops_test: OpsTest, pgb_charm_jammy):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                CLIENT_APP_NAME,
                application_name=CLIENT_APP_NAME,
                channel="edge",
            ),
            ops_test.model.deploy(
                pgb_charm_jammy,
                application_name=PGB,
                num_units=None,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel="14/edge",
                config={"profile": "testing"},
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG, CLIENT_APP_NAME], timeout=1200)
        # Relate the charms and wait for them exchanging some connection data.
        global client_relation
        client_relation = await ops_test.model.add_relation(
            f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB
        )

    await ops_test.model.wait_for_idle(status="active", timeout=600)

    # Check that on juju 3 we have secrets and no username and password in the rel databag
    if hasattr(ops_test.model, "list_secrets"):
        logger.info("checking for secrets")
        secret_uri, password, auth_file = await asyncio.gather(
            get_application_relation_data(
                ops_test,
                CLIENT_APP_NAME,
                FIRST_DATABASE_RELATION_NAME,
                "secret-user",
            ),
            get_application_relation_data(
                ops_test,
                CLIENT_APP_NAME,
                FIRST_DATABASE_RELATION_NAME,
                "password",
            ),
            get_application_relation_data(
                ops_test,
                PGB,
                PEER_RELATION_NAME,
                "auth_file",
            ),
        )
        assert secret_uri is not None
        assert password is None
        assert auth_file is None


@pytest.mark.group(1)
async def test_database_usage(ops_test: OpsTest):
    """Check we can update and delete things."""
    update_query = (
        "DROP TABLE IF EXISTS test;"
        "CREATE TABLE test(data TEXT);"
        "INSERT INTO test(data) VALUES('some data');"
        "SELECT data FROM test;"
    )
    run_update_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=update_query,
        dbname=TEST_DBNAME,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "some data" in json.loads(run_update_query["results"])[0]


@pytest.mark.group(1)
async def test_database_version(ops_test: OpsTest):
    """Check version is accurate."""
    version_query = "SELECT version();"
    run_version_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=version_query,
        dbname=TEST_DBNAME,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    # Get the version of the database and compare with the information that was retrieved directly
    # from the database.
    app_unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, app_unit.name, client_relation.id)
    version = databag.get("version", None)
    assert version, f"Version is not available in databag: {databag}"
    assert version in json.loads(run_version_query["results"])[0][0]


@pytest.mark.group(1)
async def test_database_admin_permissions(ops_test: OpsTest):
    """Test admin permissions."""
    create_database_query = "CREATE DATABASE another_database;"
    run_create_database_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=create_database_query,
        dbname=TEST_DBNAME,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "no results to fetch" in json.loads(run_create_database_query["results"])

    create_user_query = "CREATE USER another_user WITH ENCRYPTED PASSWORD 'test-password';"
    run_create_user_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=create_user_query,
        dbname=TEST_DBNAME,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "no results to fetch" in json.loads(run_create_user_query["results"])


@pytest.mark.group(1)
async def test_no_read_only_endpoint_in_standalone_cluster(ops_test: OpsTest):
    """Test that there is no read-only endpoint in a standalone cluster."""
    await scale_application(ops_test, CLIENT_APP_NAME, 1)
    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )

    unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, unit.name, client_relation.id)
    assert not databag.get(
        "read-only-endpoints", None
    ), f"read-only-endpoints in pgb databag: {databag}"


@pytest.mark.group(1)
async def test_no_read_only_endpoint_in_scaled_up_cluster(ops_test: OpsTest):
    """Test that there is read-only endpoint in a scaled up cluster."""
    await scale_application(ops_test, CLIENT_APP_NAME, 2)
    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )

    unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, unit.name, client_relation.id)
    assert not databag.get(
        "read-only-endpoints", None
    ), f"read-only-endpoints in pgb databag: {databag}"


@pytest.mark.group(1)
async def test_two_applications_cant_relate_to_the_same_pgb(ops_test: OpsTest):
    """Test that two different application connect to the database with different credentials."""
    # Set some variables to use in this test.
    all_app_names = [ANOTHER_APPLICATION_APP_NAME]
    all_app_names.extend(APP_NAMES)

    # Deploy another application.
    await ops_test.model.deploy(
        CLIENT_APP_NAME,
        application_name=ANOTHER_APPLICATION_APP_NAME,
        channel="edge",
    )
    await ops_test.model.wait_for_idle(status="active")

    # Try relate the new application with the database.
    try:
        await ops_test.model.add_relation(
            f"{ANOTHER_APPLICATION_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB
        )
        assert False, "PGB was able to relate to a second application"
    except JujuAPIError:
        pass


@pytest.mark.group(1)
async def test_an_application_can_connect_to_multiple_database_clusters(
    ops_test: OpsTest, pgb_charm_jammy
):
    """Test that an application can connect to different clusters of the same database."""
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                pgb_charm_jammy,
                application_name=PGB_2,
                num_units=None,
                config={"listen_port": 7432, "metrics_port": 9128},
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG_2,
                num_units=2,
                channel="14/edge",
                config={"profile": "testing"},
            ),
        )
        await ops_test.model.add_relation(f"{PGB_2}:{BACKEND_RELATION_NAME}", f"{PG_2}:database")
        await ops_test.model.applications[PGB].remove_relation(
            f"{PGB}:database", f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}"
        )
        await ops_test.model.wait_for_idle(apps=[PG_2], status="active", timeout=1400)
    # Relate the application with both database clusters
    # and wait for them exchanging some connection data.
    first_cluster_relation = await ops_test.model.add_relation(
        f"{CLIENT_APP_NAME}:{MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME}", PGB
    )
    second_cluster_relation = await ops_test.model.add_relation(
        f"{CLIENT_APP_NAME}:{MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME}", PGB_2
    )
    await ops_test.model.wait_for_idle(status="active", timeout=1000)

    # Retrieve the connection string to both database clusters using the relation ids and assert
    # they are different.
    application_connection_string = await build_connection_string(
        ops_test,
        CLIENT_APP_NAME,
        MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME,
        relation_id=first_cluster_relation.id,
    )
    another_application_connection_string = await build_connection_string(
        ops_test,
        CLIENT_APP_NAME,
        MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME,
        relation_id=second_cluster_relation.id,
    )
    assert application_connection_string != another_application_connection_string
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:database", f"{CLIENT_APP_NAME}:{MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME}"
    )
    await ops_test.model.applications[PGB_2].remove_relation(
        f"{PGB_2}:database", f"{CLIENT_APP_NAME}:{MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME}"
    )
    await ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME], status="active", timeout=1400)


@pytest.mark.group(1)
async def test_an_application_can_request_multiple_databases(ops_test: OpsTest):
    """Test that an application can request additional databases using the same interface.

    This occurs using a new relation per interface (for now).
    """
    # Relate the charms and wait for them exchanging some connection data.
    global client_relation
    client_relation = await ops_test.model.add_relation(
        f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB
    )
    # Relate the charms using another relation and wait for them exchanging some connection data.
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{SECOND_DATABASE_RELATION_NAME}", PGB_2)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=APP_NAMES + [PGB, PGB_2], status="active")

    # Get the connection strings to connect to both databases.
    first_database_connection_string = await build_connection_string(
        ops_test, CLIENT_APP_NAME, FIRST_DATABASE_RELATION_NAME
    )
    second_database_connection_string = await build_connection_string(
        ops_test, CLIENT_APP_NAME, SECOND_DATABASE_RELATION_NAME
    )

    # Assert the two application have different relation (connection) data.
    assert first_database_connection_string != second_database_connection_string


@pytest.mark.group(1)
async def test_scaling(ops_test: OpsTest):
    """Check these relations all work when scaling pgbouncer."""
    await scale_application(ops_test, CLIENT_APP_NAME, 1)
    await ops_test.model.wait_for_idle()
    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )

    await scale_application(ops_test, CLIENT_APP_NAME, 2)
    await ops_test.model.wait_for_idle()
    await check_new_relation(
        ops_test,
        unit_name=ops_test.model.applications[CLIENT_APP_NAME].units[0].name,
        relation_id=client_relation.id,
        relation_name=FIRST_DATABASE_RELATION_NAME,
        dbname=TEST_DBNAME,
    )


@pytest.mark.group(1)
async def test_relation_broken(ops_test: OpsTest):
    """Test that the user is removed when the relation is broken."""
    # Retrieve the relation user.
    relation_user = await get_application_relation_data(
        ops_test, CLIENT_APP_NAME, FIRST_DATABASE_RELATION_NAME, "username"
    )

    # Break the relation.
    backend_rel = get_backend_relation(ops_test)
    pg_user, pg_pass = await get_backend_user_pass(ops_test, backend_rel)
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:database", f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}"
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=APP_NAMES, status="active", raise_on_blocked=True)

    # Check that the relation user was removed from the database.
    await check_database_users_existence(
        ops_test, [], [relation_user], pg_user=pg_user, pg_user_password=pg_pass
    )
