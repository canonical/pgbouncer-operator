#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import pytest
from mailmanclient import Client
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from tests.integration.helpers.helpers import (
    MAILMAN3,
    PG,
    PGB,
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_legacy_relation_username,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

APPLICATION_UNITS = 1
DATABASE_UNITS = 2
RELATION_NAME = "db"


@pytest.mark.abort_on_fail
async def test_mailman3_core_db(ops_test: OpsTest, pgb_charm_focal) -> None:
    """Deploy Mailman3 Core to test the 'db' relation."""
    async with ops_test.fast_forward():
        # Extra config option for Mailman3 Core.
        mailman_config = {"hostname": "example.org"}
        # Deploy and test the deployment of Mailman3 Core.
        backend_relation = await deploy_postgres_bundle(
            ops_test,
            pgb_charm_focal,
            db_units=DATABASE_UNITS,
            pgb_config={"listen_port": 5432},
            pgb_series="focal",
        )
        db_relation = await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test,
            MAILMAN3,
            MAILMAN3,
            config=mailman_config,
            series="focal",
        )
        pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)
        await check_databases_creation(ops_test, ["mailman3"], pgb_user, pgb_pass)

        mailman3_core_users = get_legacy_relation_username(ops_test, db_relation.id)

        await check_database_users_existence(
            ops_test, [mailman3_core_users], [], pgb_user, pgb_pass
        )

        # Assert Mailman3 Core is configured to use PostgreSQL instead of SQLite.
        mailman_unit = ops_test.model.applications[MAILMAN3].units[0]
        action = await mailman_unit.run("mailman info")
        result = action.results.get("Stdout", action.results.get("Stderr", None))
        assert "db url: postgres://" in result, f"no postgres db url, Stderr: {result}"

        # Do some CRUD operations using Mailman3 Core client.
        domain_name = "canonical.com"
        list_name = "postgresql-list"
        credentials = (
            result.split("credentials: ")[1].strip().split(":")
        )  # This outputs a list containing username and password.
        client = Client(
            f"http://{mailman_unit.public_address}:8001/3.1", credentials[0], credentials[1]
        )

        # Create a domain and list the domains to check that the new one is there.
        domain = client.create_domain(domain_name)
        assert domain_name in [domain.mail_host for domain in client.domains]

        # Update the domain by creating a mailing list into it.
        mailing_list = domain.create_list(list_name)
        assert mailing_list.fqdn_listname in [
            mailing_list.fqdn_listname for mailing_list in domain.lists
        ]

        # Delete the domain and check that the change was persisted.
        domain.delete()
        assert domain_name not in [domain.mail_host for domain in client.domains]


async def test_remove_relation(ops_test: OpsTest):
    await ops_test.model.applications[PGB].remove_relation(f"{PGB}:db", f"{MAILMAN3}:db")
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle([PG], status="active", timeout=300)
    for attempt in Retrying(stop=stop_after_attempt(60), wait=wait_fixed(5), reraise=True):
        with attempt:
            await ops_test.model.applications[PGB].get_status()
            assert len(ops_test.model.applications[PGB].units) == 0, "pgb units were not removed"
