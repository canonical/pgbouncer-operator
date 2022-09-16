#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import psycopg2 as psycopg2
import pytest
import yaml
from mailmanclient import Client
from pytest_operator.plugin import OpsTest

from constants import PG
from tests.integration.helpers.helpers import (
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_legacy_relation_username,
    scale_application,
)
from tests.integration.helpers.postgresql_helpers import (
    build_connection_string,
    check_database_users_existence,
    check_databases_creation,
)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]

logger = logging.getLogger(__name__)

MAILMAN3_CORE_APP_NAME = "mailman3-core"
APPLICATION_UNITS = 1
DATABASE_UNITS = 1
RELATION_NAME = "db"


@pytest.mark.legacy_relation
async def test_mailman3_core_db(ops_test: OpsTest) -> None:
    """Deploy Mailman3 Core to test the 'db' relation."""
    backend_relation = await deploy_postgres_bundle(
        ops_test, db_units=DATABASE_UNITS, pgb_config={"listen_port": "5432"}
    )

    async with ops_test.fast_forward():
        # Extra config option for Mailman3 Core.
        mailman_config = {"hostname": "example.org"}
        # Deploy and test the deployment of Mailman3 Core.
        db_relation = await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test,
            "mailman3-core",
            MAILMAN3_CORE_APP_NAME,
            APPLICATION_UNITS,
            mailman_config,
        )
        pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)
        await check_databases_creation(ops_test, ["mailman3"], pgb_user, pgb_pass)

        mailman3_core_users = get_legacy_relation_username(ops_test, db_relation.id)

        await check_database_users_existence(
            ops_test, [mailman3_core_users], [], pgb_user, pgb_pass
        )

        # Assert Mailman3 Core is configured to use PostgreSQL instead of SQLite.
        mailman_unit = ops_test.model.applications[MAILMAN3_CORE_APP_NAME].units[0]
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

