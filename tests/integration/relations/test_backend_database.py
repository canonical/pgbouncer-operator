# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
import os

from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ..helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    MAILMAN3,
    PG,
    PGB,
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_app_relation_databag,
    get_backend_user_pass,
    get_cfg,
    run_command_on_unit,
    wait_for_relation_removed_between,
)
from ..helpers.postgresql_helpers import (
    check_database_users_existence,
    get_postgres_primary,
)
from ..juju_ import juju_major_version

logger = logging.getLogger(__name__)

if juju_major_version < 3:
    TLS = "tls-certificates-operator"
    tls_channel = "legacy/stable"
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
else:
    TLS = "self-signed-certificates"
    tls_channel = "latest/stable"
    tls_config = {"ca-common-name": "Test CA"}
RELATION = "backend-database"


async def test_relate_pgbouncer_to_postgres(ops_test: OpsTest, charm):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    relation = await deploy_postgres_bundle(ops_test, charm, pgb_base="ubuntu@22.04")
    async with ops_test.fast_forward():
        await ops_test.model.deploy(
            CLIENT_APP_NAME, application_name=CLIENT_APP_NAME, channel="edge"
        )
        # Relate the charms and wait for them exchanging some connection data.
        await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)
        # Pgbouncer enters a blocked status without a postgres backend database relation
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=600)

    cfg = await get_cfg(ops_test, f"{PGB}/0")
    logger.info(cfg)
    pgb_user, pgb_password = await get_backend_user_pass(ops_test, relation)
    assert cfg["pgbouncer"]["auth_query"]

    await check_database_users_existence(ops_test, [pgb_user], [], pgb_user, pgb_password)

    # Remove relation
    await ops_test.model.applications[PG].remove_relation(f"{PGB}:{RELATION}", f"{PG}:database")
    pgb_unit = ops_test.model.applications[PGB].units[0]
    logger.info(await get_app_relation_databag(ops_test, pgb_unit.name, relation.id))
    wait_for_relation_removed_between(ops_test, PG, PGB)

    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=600),
            ops_test.model.wait_for_idle(
                apps=[PG], status="active", timeout=600, wait_for_exact_units=3
            ),
        )

        # Wait for pgbouncer charm to update its config files.
        try:
            for attempt in Retrying(stop=stop_after_delay(3 * 60), wait=wait_fixed(3)):
                with attempt:
                    cfg = await get_cfg(ops_test, f"{PGB}/0")
                    if "auth_query" not in cfg["pgbouncer"]:
                        break
        except RetryError:
            assert False, "pgbouncer config files failed to update in 3 minutes"

    cfg = await get_cfg(ops_test, f"{PGB}/0")
    logger.info(cfg)
    await ops_test.model.remove_application(CLIENT_APP_NAME, block_until_done=True)
    await ops_test.model.remove_application(PGB, block_until_done=True)


async def test_tls_encrypted_connection_to_postgres(ops_test: OpsTest, charm_focal):
    await ops_test.model.deploy(charm_focal, PGB, num_units=0, base="ubuntu@20.04")
    async with ops_test.fast_forward():
        # Relate PgBouncer to PostgreSQL.
        relation = await ops_test.model.add_relation(f"{PGB}:{RELATION}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000)

        # Deploy TLS Certificates operator.
        await ops_test.model.deploy(TLS, config=tls_config, channel=tls_channel)
        await ops_test.model.wait_for_idle(apps=[TLS], status="active", timeout=1000)

        # Relate it to the PostgreSQL to enable TLS.
        certificates_relation = (
            "client-certificates"
            if os.environ["POSTGRESQL_CHARM_CHANNEL"].split("/")[0] == "16"
            else "certificates"
        )
        await ops_test.model.relate(f"{PG}:{certificates_relation}", TLS)
        await ops_test.model.wait_for_idle(apps=[PG, TLS], status="active", timeout=1000)

        # Enable additional logs on the PostgreSQL instance to check TLS
        # being used in a later step.
        await ops_test.model.applications[PG].set_config({"logging_log_connections": "True"})
        await ops_test.model.wait_for_idle(apps=[PG], status="active", idle_period=30)

        # Deploy and test the deployment of Weebl.
        await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test, MAILMAN3, MAILMAN3, series="focal"
        )

        pgb_user, _ = await get_backend_user_pass(ops_test, relation)

        # Check the logs to ensure TLS is being used by PgBouncer.
        postgresql_primary_unit = await get_postgres_primary(ops_test)
        mailman_ssl_log = f"connection authorized: user={pgb_user} database=mailman3 SSL enabled"
        postgresql_logs = "/var/snap/charmed-postgresql/common/var/log/postgresql/postgresql-*.log"
        await run_command_on_unit(
            ops_test,
            postgresql_primary_unit,
            f"grep '{mailman_ssl_log}' {postgresql_logs}",
        )
