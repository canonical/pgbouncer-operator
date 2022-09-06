#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import psycopg2 as psycopg2
import pytest as pytest
import yaml
from mailmanclient import Client
from pytest_operator.plugin import OpsTest

from constants import PG
from tests.integration.helpers.helpers import (
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_cfg,
    get_legacy_relation_username,
    get_unit_info,
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


@pytest.mark.dev
@pytest.mark.legacy_relation
async def test_mailman3_core_db(ops_test: OpsTest) -> None:
    """Deploy Mailman3 Core to test the 'db' relation."""
    backend_relation = await deploy_postgres_bundle(ops_test, db_units=DATABASE_UNITS)

    async with ops_test.fast_forward():
        await ops_test.model.applications[PGB].set_config({"listen_port": "5432"})
        # Extra config option for Mailman3 Core.
        config = {"hostname": "example.org"}
        # Deploy and test the deployment of Mailman3 Core.
        relation_id = await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test,
            "mailman3-core",
            MAILMAN3_CORE_APP_NAME,
            APPLICATION_UNITS,
            config,
        )
        pgb_user, pgb_pass = await get_backend_user_pass(ops_test, backend_relation)
        await check_databases_creation(ops_test, ["mailman3"], pgb_user, pgb_pass)

        mailman3_core_users = get_legacy_relation_username(ops_test, relation_id)

        await check_database_users_existence(
            ops_test, [mailman3_core_users], [], pgb_user, pgb_pass
        )

        # Assert Mailman3 Core is configured to use PostgreSQL instead of SQLite.
        mailman_unit = ops_test.model.applications[MAILMAN3_CORE_APP_NAME].units[0]
        action = await mailman_unit.run("mailman info")
        logging.info(action)
        logging.info(action.results)
        result = action.results.get("Stdout", action.results.get("Stderr", None))
        logging.info(await get_cfg(ops_test, mailman_unit.name))
        logging.info(await get_unit_info(ops_test, mailman_unit.name, format="yaml"))
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


# Skip scaling test until scaling is implemented.
@pytest.mark.skip
@pytest.mark.legacy_relation
async def test_relation_data_is_updated_correctly_when_scaling(ops_test: OpsTest):
    """Test that relation data, like connection data, is updated correctly when scaling."""
    # Retrieve the list of current database unit names.
    units_to_remove = [unit.name for unit in ops_test.model.applications[PG].units]

    async with ops_test.fast_forward():
        # Add two more units.
        await ops_test.model.applications[PG].add_units(2)
        await ops_test.model.wait_for_idle(
            apps=[PG], status="active", timeout=1000, wait_for_exact_units=5
        )

        # Remove the original units.
        await ops_test.model.applications[PG].destroy_units(*units_to_remove)
        await ops_test.model.wait_for_idle(
            apps=[PG], status="active", timeout=3000, wait_for_exact_units=2
        )

        # Get the updated connection data and assert it can be used
        # to write and read some data properly.
        primary_connection_string = await build_connection_string(
            ops_test, MAILMAN3_CORE_APP_NAME, RELATION_NAME
        )
        replica_connection_string = await build_connection_string(
            ops_test, MAILMAN3_CORE_APP_NAME, RELATION_NAME, read_only_endpoint=True
        )

        # Connect to the database using the primary connection string.
        with psycopg2.connect(primary_connection_string) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                # Check that it's possible to write and read data from the database that
                # was created for the application.
                cursor.execute("DROP TABLE IF EXISTS test;")
                cursor.execute("CREATE TABLE test(data TEXT);")
                cursor.execute("INSERT INTO test(data) VALUES('some data');")
                cursor.execute("SELECT data FROM test;")
                data = cursor.fetchone()
                assert data[0] == "some data"
        connection.close()

        # Connect to the database using the replica endpoint.
        with psycopg2.connect(replica_connection_string) as connection:
            with connection.cursor() as cursor:
                # Read some data.
                cursor.execute("SELECT data FROM test;")
                data = cursor.fetchone()
                assert data[0] == "some data"

                # Try to alter some data in a read-only transaction.
                with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
                    cursor.execute("DROP TABLE test;")
        connection.close()

        # Remove the relation and test that its user was deleted
        # (by checking that the connection string doesn't work anymore).
        await ops_test.model.applications[PG].remove_relation(
            f"{PG}:{RELATION_NAME}", f"{MAILMAN3_CORE_APP_NAME}:{RELATION_NAME}"
        )
        await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000)
        with pytest.raises(psycopg2.OperationalError):
            psycopg2.connect(primary_connection_string)
