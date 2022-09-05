#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import ast
import json
import logging

import pytest
from landscape_api.base import run_query
from pytest_operator.plugin import OpsTest

from tests.integration.helpers.helpers import (
    deploy_and_relate_bundle_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_legacy_relation_username,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

HAPROXY_APP_NAME = "haproxy"
LANDSCAPE_APP_NAME = "landscape-server"
LANDSCAPE_SCALABLE_BUNDLE_NAME = "ch:landscape-scalable"
RABBITMQ_APP_NAME = "rabbitmq-server"
DATABASE_UNITS = 3


@pytest.mark.dev
@pytest.mark.legacy_relation
async def test_landscape_scalable_bundle_db(ops_test: OpsTest) -> None:
    """Deploy Landscape Scalable Bundle to test the 'db-admin' relation."""
    config = {
        "extra-packages": "python-apt postgresql-contrib postgresql-.*-debversion postgresql-plpython.*"
    }
    backend_relation = await deploy_postgres_bundle(
        ops_test, pg_config=config, db_units=DATABASE_UNITS
    )

    async with ops_test.fast_forward():
        # Deploy and test the Landscape Scalable bundle (using this charm).
        relation_id = await deploy_and_relate_bundle_with_pgbouncer_bundle(
            ops_test, LANDSCAPE_SCALABLE_BUNDLE_NAME, LANDSCAPE_APP_NAME, relation_name="db-admin"
        )
    await check_databases_creation(
        ops_test,
        [
            "landscape-account-1",
            "landscape-knowledge",
            "landscape-main",
            "landscape-package",
            "landscape-resource-1",
            "landscape-session",
        ],
    )

    landscape_users = get_legacy_relation_username(relation_id)
    pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)

    await check_database_users_existence(ops_test, landscape_users, [], pgb_user, pgb_pass)

    # Configure and admin user in Landscape and get its API credentials.
    unit = ops_test.model.applications[LANDSCAPE_APP_NAME].units[0]
    action = await unit.run_action(
        "bootstrap",
        **{
            "admin-email": "admin@canonical.com",
            "admin-name": "Admin",
            "admin-password": "test1234",
        },
    )
    result = await action.wait()
    credentials = ast.literal_eval(result.results["api-credentials"])
    key = credentials["key"]
    secret = credentials["secret"]

    # Connect to the Landscape API through HAProxy and do some CRUD calls (without the update).
    haproxy_unit = ops_test.model.applications[HAPROXY_APP_NAME].units[0]
    api_uri = f"https://{haproxy_unit.public_address}/api/"
    role_name = "User"

    # Create a role and list the available roles later to check that the new one is there.
    run_query(key, secret, "CreateRole", {"name": role_name}, api_uri, False)
    api_response = run_query(key, secret, "GetRoles", {}, api_uri, False)
    assert role_name in [user["name"] for user in json.loads(api_response)]

    # Remove the role and assert it isn't part of the roles list anymore.
    run_query(key, secret, "RemoveRole", {"name": role_name}, api_uri, False)
    api_response = run_query(key, secret, "GetRoles", {}, api_uri, False)
    assert role_name not in [user["name"] for user in json.loads(api_response)]

    # Remove the applications from the bundle.
    await ops_test.model.remove_application(LANDSCAPE_APP_NAME, block_until_done=True)
    await ops_test.model.remove_application(HAPROXY_APP_NAME, block_until_done=True)
    await ops_test.model.remove_application(RABBITMQ_APP_NAME, block_until_done=True)
