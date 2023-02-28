# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

import yaml
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.helpers.helpers import (
    deploy_and_relate_application_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_app_relation_databag,
    get_backend_user_pass,
    get_cfg,
    wait_for_relation_removed_between,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    enable_connections_logging,
    get_postgres_primary,
    run_command_on_unit,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MAILMAN3 = "mailman3-core"
WEEBL = "weebl"
PGB = METADATA["name"]
PG = "postgresql"
TLS = "tls-certificates-operator"
RELATION = "backend-database"


async def test_relate_pgbouncer_to_postgres(ops_test: OpsTest, pgb_charm_focal):
    """Test that the pgbouncer and postgres charms can relate to one another."""
    # Build, deploy, and relate charms.
    relation = await deploy_postgres_bundle(ops_test, pgb_charm_focal)
    await deploy_and_relate_application_with_pgbouncer_bundle(
        ops_test,
        WEEBL,
        WEEBL,
        series="focal",
    )

    cfg = await get_cfg(ops_test, f"{PGB}/0")
    logger.info(cfg.render())
    pgb_user, pgb_password = await get_backend_user_pass(ops_test, relation)
    assert pgb_user in cfg["pgbouncer"]["admin_users"]
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
                    if (
                        pgb_user not in cfg["pgbouncer"]["admin_users"]
                        and "auth_query" not in cfg["pgbouncer"].keys()
                    ):
                        break
        except RetryError:
            assert False, "pgbouncer config files failed to update in 3 minutes"

    cfg = await get_cfg(ops_test, f"{PGB}/0")
    logger.info(cfg.render())
    await ops_test.model.remove_application(WEEBL, block_until_done=True)


async def test_tls_encrypted_connection_to_postgres(ops_test: OpsTest, pgb_charm_focal):
    async with ops_test.fast_forward():
        # Relate PgBouncer to PostgreSQL.
        relation = await ops_test.model.add_relation(f"{PGB}:{RELATION}", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000)

        # Deploy TLS Certificates operator.
        config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
        await ops_test.model.deploy(TLS, config=config)
        await ops_test.model.wait_for_idle(apps=[TLS], status="active", timeout=1000)

        # Relate it to the PostgreSQL to enable TLS.
        await ops_test.model.relate(PG, TLS)
        await ops_test.model.wait_for_idle(status="active", timeout=1000)

        # Enable additional logs on the PostgreSQL instance to check TLS
        # being used in a later step.
        enable_connections_logging(ops_test, f"{PG}/0")

        # Deploy and test the deployment of Mailman3 Core.
        await deploy_and_relate_application_with_pgbouncer_bundle(
            ops_test,
            MAILMAN3,
            MAILMAN3,
            series="focal",
            force=True,
        )

        pgb_user, _ = await get_backend_user_pass(ops_test, relation)

        # Check the logs to ensure TLS is being used by PgBouncer.
        postgresql_primary_unit = await get_postgres_primary(ops_test)
        logs = await run_command_on_unit(
            ops_test, postgresql_primary_unit, "journalctl -u patroni.service"
        )
        assert (
            f"connection authorized: user={pgb_user} database=mailman3 SSL enabled"
            " (protocol=TLSv1.3, cipher=TLS_AES_256_GCM_SHA384, bits=256, compression=off)" in logs
        ), "TLS is not being used on connections to PostgreSQL"
