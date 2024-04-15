#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging

import pytest
from landscape_api.base import run_query
from pytest_operator.plugin import OpsTest

from ..helpers.helpers import (
    PG,
    PGB,
    deploy_postgres_bundle,
)
from ..helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
    deploy_and_relate_bundle_with_pgbouncer,
    get_landscape_api_credentials,
)

logger = logging.getLogger(__name__)

HAPROXY_APP_NAME = "haproxy"
LANDSCAPE_APP_NAME = "landscape-server"
RABBITMQ_APP_NAME = "rabbitmq-server"
DATABASE_UNITS = 2
RELATION_NAME = "db-admin"


@pytest.mark.group(1)
async def test_landscape_scalable_bundle_db(ops_test: OpsTest, pgb_charm_jammy: str) -> None:
    """Deploy Landscape Scalable Bundle to test the 'db-admin' relation."""
    await deploy_postgres_bundle(
        ops_test,
        pgb_charm_jammy,
        db_units=DATABASE_UNITS,
        pgb_series="jammy",
        pg_config={"profile": "testing", "plugin_plpython3u_enable": "True"},
    )

    # Deploy and test the Landscape Scalable bundle (using this PostgreSQL charm).
    relation_id = await deploy_and_relate_bundle_with_pgbouncer(
        ops_test,
        "ch:landscape-scalable",
        LANDSCAPE_APP_NAME,
        main_application_num_units=2,
        relation_name=RELATION_NAME,
        timeout=3000,
    )
    await check_databases_creation(
        ops_test,
        [
            "landscape-standalone-account-1",
            "landscape-standalone-knowledge",
            "landscape-standalone-main",
            "landscape-standalone-package",
            "landscape-standalone-resource-1",
            "landscape-standalone-session",
        ],
    )

    landscape_users = [f"relation-{relation_id}"]

    await check_database_users_existence(ops_test, landscape_users, [])

    # Create the admin user on Landscape through configs.
    await ops_test.model.applications["landscape-server"].set_config({
        "admin_email": "admin@canonical.com",
        "admin_name": "Admin",
        "admin_password": "test1234",
    })
    await ops_test.model.wait_for_idle(
        apps=["landscape-server", PG, PGB],
        status="active",
        timeout=1200,
    )

    # Connect to the Landscape API through HAProxy and do some CRUD calls (without the update).
    key, secret = await get_landscape_api_credentials(ops_test)
    haproxy_unit = ops_test.model.applications[HAPROXY_APP_NAME].units[0]
    api_uri = f"https://{haproxy_unit.public_address}/api/"

    # Create a role and list the available roles later to check that the new one is there.
    role_name = "User1"
    run_query(key, secret, "CreateRole", {"name": role_name}, api_uri, False)
    api_response = run_query(key, secret, "GetRoles", {}, api_uri, False)
    assert role_name in [user["name"] for user in json.loads(api_response)]

    # Remove the role and assert it isn't part of the roles list anymore.
    run_query(key, secret, "RemoveRole", {"name": role_name}, api_uri, False)
    api_response = run_query(key, secret, "GetRoles", {}, api_uri, False)
    assert role_name not in [user["name"] for user in json.loads(api_response)]
