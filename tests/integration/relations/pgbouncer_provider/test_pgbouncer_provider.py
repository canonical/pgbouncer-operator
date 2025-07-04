#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import json
import logging
import os
import time

import pytest
from juju.errors import JujuAPIError
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME, PEER_RELATION_NAME

from ...helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
    SECOND_DATABASE_RELATION_NAME,
    get_app_relation_databag,
    get_backend_relation,
    get_backend_user_pass,
    get_cfg,
    scale_application,
)
from ...helpers.postgresql_helpers import check_database_users_existence
from .helpers import (
    build_connection_string,
    check_new_relation,
    get_application_relation_data,
    run_sql_on_application_charm,
)

logger = logging.getLogger(__name__)

CLIENT_UNIT_NAME = f"{CLIENT_APP_NAME}/0"
TEST_DBNAME = "postgresql_test_app_database"
ANOTHER_APPLICATION_APP_NAME = "another-application"
PG_2 = "another-postgresql"
PGB_2 = "another-pgbouncer"
APP_NAMES = [CLIENT_APP_NAME, PG]
MULTIPLE_DATABASE_CLUSTERS_RELATION_NAME = "multiple-database-clusters"


@pytest.mark.abort_on_fail
async def test_database_relation_with_charm_libraries(ops_test: OpsTest, charm):
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
                charm,
                application_name=PGB,
                config={"local_connection_type": "uds"},
                num_units=0,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
                config={"profile": "testing"},
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG, CLIENT_APP_NAME], timeout=1200)
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)

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
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "some data" in json.loads(run_update_query["results"])[0]


async def test_database_version(ops_test: OpsTest):
    """Check version is accurate."""
    version_query = "SELECT version();"
    run_version_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=version_query,
        dbname=TEST_DBNAME,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    # Get the version of the database and compare with the information that was retrieved directly
    # from the database.
    relations = [
        relation
        for relation in ops_test.model.applications[PGB].relations
        if not relation.is_peer
        and f"{relation.requires.application_name}:{relation.requires.name}"
        == f"{CLIENT_APP_NAME}:database"
    ]
    app_unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, app_unit.name, relations[0].id)
    version = databag.get("version", None)
    assert version, f"Version is not available in databag: {databag}"
    assert version in json.loads(run_version_query["results"])[0][0]


async def test_database_admin_permissions(ops_test: OpsTest):
    """Test admin permissions."""
    if os.environ["POSTGRESQL_CHARM_CHANNEL"].split("/")[0] != "14":
        pytest.skip(
            "Skipping check for database and user creation permissions on PostgreSQL above 14, as they are not supported."
        )
    create_database_query = "CREATE DATABASE another_database;"
    run_create_database_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=create_database_query,
        dbname=TEST_DBNAME,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "no results to fetch" in json.loads(run_create_database_query["results"])

    create_user_query = "CREATE USER another_user WITH ENCRYPTED PASSWORD 'test-password';"
    run_create_user_query = await run_sql_on_application_charm(
        ops_test,
        unit_name=CLIENT_UNIT_NAME,
        query=create_user_query,
        dbname=TEST_DBNAME,
        relation_name=FIRST_DATABASE_RELATION_NAME,
    )
    assert "no results to fetch" in json.loads(run_create_user_query["results"])


async def test_localhost_read_only_endpoint_in_standalone_cluster(ops_test: OpsTest):
    """Test that there is no read-only endpoint in a standalone cluster."""
    await scale_application(ops_test, CLIENT_APP_NAME, 1)
    cfg = await get_cfg(ops_test, ops_test.model.applications[PGB].units[0].name)
    logger.info(cfg)
    for unit in ops_test.model.applications[CLIENT_APP_NAME].units:
        logger.info(f"Checking connection for {unit.name}")
        await check_new_relation(
            ops_test,
            unit_name=unit.name,
            relation_name=FIRST_DATABASE_RELATION_NAME,
            dbname=TEST_DBNAME,
        )

    relations = [
        relation
        for relation in ops_test.model.applications[PGB].relations
        if not relation.is_peer
        and f"{relation.requires.application_name}:{relation.requires.name}"
        == f"{CLIENT_APP_NAME}:database"
    ]
    unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, unit.name, relations[0].id)
    assert (
        databag.get("read-only-endpoints", None)
        == "/var/snap/charmed-pgbouncer/current/run/pgbouncer/pgbouncer/instance_0:6432"
    ), f"read-only-endpoints not in pgb databag: {databag}"


async def test_localhost_read_only_endpoint_in_scaled_up_cluster(ops_test: OpsTest):
    """Test that there is read-only endpoint in a scaled up cluster."""
    await scale_application(ops_test, CLIENT_APP_NAME, 2)
    await ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME, PGB], status="active")
    cfg = await get_cfg(ops_test, ops_test.model.applications[PGB].units[0].name)
    logger.info(cfg)
    for unit in ops_test.model.applications[CLIENT_APP_NAME].units:
        logger.info(f"Checking connection for {unit.name}")
        await check_new_relation(
            ops_test,
            unit_name=unit.name,
            relation_name=FIRST_DATABASE_RELATION_NAME,
            dbname=TEST_DBNAME,
        )
    relations = [
        relation
        for relation in ops_test.model.applications[PGB].relations
        if not relation.is_peer
        and f"{relation.requires.application_name}:{relation.requires.name}"
        == f"{CLIENT_APP_NAME}:database"
    ]
    unit = ops_test.model.applications[CLIENT_APP_NAME].units[0]
    databag = await get_app_relation_databag(ops_test, unit.name, relations[0].id)
    assert (
        databag.get("read-only-endpoints", None)
        == "/var/snap/charmed-pgbouncer/current/run/pgbouncer/pgbouncer/instance_0:6432"
    ), f"read-only-endpoints not in pgb databag: {databag}"


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


async def test_an_application_can_connect_to_multiple_database_clusters(ops_test: OpsTest, charm):
    """Test that an application can connect to different clusters of the same database."""
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=PGB_2,
                num_units=0,
                config={"listen_port": 7432, "metrics_port": 9128},
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG_2,
                num_units=2,
                channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
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


async def test_an_application_can_request_multiple_databases(ops_test: OpsTest):
    """Test that an application can request additional databases using the same interface.

    This occurs using a new relation per interface (for now).
    """
    # Relate the charms and wait for them exchanging some connection data.
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
    # Relate the charms using another relation and wait for them exchanging some connection data.
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{SECOND_DATABASE_RELATION_NAME}", PGB_2)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[*APP_NAMES, PGB, PGB_2], status="active")

    # Get the connection strings to connect to both databases.
    first_database_connection_string = await build_connection_string(
        ops_test, CLIENT_APP_NAME, FIRST_DATABASE_RELATION_NAME
    )
    second_database_connection_string = await build_connection_string(
        ops_test, CLIENT_APP_NAME, SECOND_DATABASE_RELATION_NAME
    )

    # Assert the two application have different relation (connection) data.
    assert first_database_connection_string != second_database_connection_string


async def test_scaling(ops_test: OpsTest):
    """Check these relations all work when scaling pgbouncer."""
    await scale_application(ops_test, CLIENT_APP_NAME, 1)
    await ops_test.model.wait_for_idle()
    cfg = await get_cfg(ops_test, ops_test.model.applications[PGB].units[0].name)
    logger.info(cfg)
    for unit in ops_test.model.applications[CLIENT_APP_NAME].units:
        logger.info(f"Checking connection for {unit.name}")
        await check_new_relation(
            ops_test,
            unit_name=unit.name,
            relation_name=FIRST_DATABASE_RELATION_NAME,
            dbname=TEST_DBNAME,
        )

    await scale_application(ops_test, CLIENT_APP_NAME, 2)
    await ops_test.model.wait_for_idle(apps=[CLIENT_APP_NAME, PGB], status="active")
    cfg = await get_cfg(ops_test, ops_test.model.applications[PGB].units[0].name)
    logger.info(cfg)
    for unit in ops_test.model.applications[CLIENT_APP_NAME].units:
        logger.info(f"Checking connection for {unit.name}")
        await check_new_relation(
            ops_test,
            unit_name=unit.name,
            relation_name=FIRST_DATABASE_RELATION_NAME,
            dbname=TEST_DBNAME,
        )


@pytest.mark.skip(reason="Unstable")
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
        time.sleep(20)

    # Check that the relation user was removed from the database.
    await check_database_users_existence(
        ops_test, [], [relation_user], pg_user=pg_user, pg_user_password=pg_pass
    )
