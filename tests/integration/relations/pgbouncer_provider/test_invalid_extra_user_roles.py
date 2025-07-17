#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
from itertools import combinations

import jubilant
import pytest as pytest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ...helpers.helpers import (
    PG,
    PGB,
)
from ...jubilant_helpers import relations
from .helpers import DATA_INTEGRATOR_APP_NAME

logger = logging.getLogger(__name__)

REQUESTED_DATABASE_NAME = "requested-database"
RELATION_ENDPOINT = "postgresql"
TIMEOUT = 15 * 60


def data_integrator_blocked(status: jubilant.Status, app_name=DATA_INTEGRATOR_APP_NAME) -> bool:
    return jubilant.all_blocked(status, app_name)


def database_active(status: jubilant.Status, app_name=PG) -> bool:
    return jubilant.all_active(status, app_name)


@pytest.mark.abort_on_fail
def test_deploy(juju: jubilant.Juju, charm_noble) -> None:
    """Deploy the charms."""
    # Deploy the database charm if not already deployed.
    if PG not in juju.status().apps:
        logger.info("Deploying database charm")
        juju.deploy(
            PG,
            channel=os.environ["POSTGRESQL_CHARM_CHANNEL"],
            config={"profile": "testing"},
            num_units=1,
            base="ubuntu@24.04",
        )

    # Deploy the PgBouncer charm if not already deployed.
    if PGB not in juju.status().apps:
        logger.info("Deploying PgBouncer charm")
        juju.deploy(charm_noble, base="ubuntu@24.04")

    # Deploy the data integrator if not already deployed.
    if DATA_INTEGRATOR_APP_NAME not in juju.status().apps:
        logger.info("Deploying data integrator charm")
        juju.deploy(
            DATA_INTEGRATOR_APP_NAME,
            config={"database-name": REQUESTED_DATABASE_NAME},
        )

    # Relate the PgBouncer charm to the database charm.
    existing_relations = relations(juju, PG, PGB)
    if existing_relations:
        logger.info("Removing existing relation between charms")
        juju.remove_relation(PGB, PG)
    logger.info("Adding relation between charms")
    for attempt in Retrying(stop=stop_after_delay(120), wait=wait_fixed(5)):
        with attempt:
            juju.integrate(PGB, PG)

    # Remove the relation between the data integrator and the PgBouncer charms.
    existing_relations = relations(juju, PGB, DATA_INTEGRATOR_APP_NAME)
    if existing_relations:
        logger.info("Removing existing relation between charms")
        juju.remove_relation(f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB)
        juju.wait(lambda status: data_integrator_blocked(status), timeout=TIMEOUT)

    logger.info(
        "Waiting for the database charm to become active and the data integrator charm to block"
    )
    juju.wait(lambda status: database_active(status), timeout=TIMEOUT)
    juju.wait(lambda status: data_integrator_blocked(status), timeout=TIMEOUT)


def test_extra_user_roles(  # noqa: C901
    juju: jubilant.Juju, predefined_roles, predefined_roles_combinations
) -> None:
    """Check that invalid extra user roles make the PgBouncer charm block."""
    # Remove the empty role (no extra user roles, i.e., regular relation user).
    del predefined_roles[""]
    invalid_extra_user_roles_combinations = [
        ("backup",),
        ("charmed_backup",),
        ("charmed_dba",),
        ("invalid",),
        ("invalid", "invalid"),
        ("monitoring",),
        ("postgres",),
        ("pg_monitor",),
        ("replication",),
        ("rewind",),
    ]
    invalid_extra_user_roles_combinations.extend([
        combination
        for combination in combinations(predefined_roles.keys(), 2)
        if combination not in predefined_roles_combinations
    ])
    logger.info(f"Invalid combinations: {invalid_extra_user_roles_combinations}")

    for invalid_extra_user_roles_combination in invalid_extra_user_roles_combinations:
        # TODO: Sometimes, PgBouncer starts and get blocked with the status message
        # equal to "PgBouncer service pgbouncer-pgbouncer@0 not running". We need to
        # understand why it's happening and fix that.
        for i in range(3):
            logger.info(
                f"Requesting invalid extra user roles combination: {', '.join(invalid_extra_user_roles_combination)}"
            )
            juju.config(
                app=DATA_INTEGRATOR_APP_NAME,
                values={
                    "extra-user-roles": ",".join(invalid_extra_user_roles_combination),
                },
            )
            juju.wait(lambda status: data_integrator_blocked(status), timeout=TIMEOUT)

            logger.info("Adding relation between charms")
            for attempt in Retrying(stop=stop_after_delay(120), wait=wait_fixed(5)):
                with attempt:
                    juju.integrate(DATA_INTEGRATOR_APP_NAME, PGB)

            logger.info("Waiting for the PgBouncer charm to block due to invalid extra user roles")

            def all_units_blocked(status: jubilant.Status) -> bool:
                for app in status.apps:
                    if app == PG:
                        continue
                    for unit_info in status.get_units(app).values():
                        if unit_info.workload_status.current != "blocked":
                            return False
                return True

            juju.wait(lambda status: all_units_blocked(status))
            try:
                for attempt in Retrying(stop=stop_after_delay(120), wait=wait_fixed(5)):
                    with attempt:
                        assert (
                            juju.status()
                            .get_units(PGB)
                            .get(next(iter(juju.status().get_units(PGB))))
                            .workload_status.message
                            == "invalid role(s) for extra user roles"
                        ), (
                            "The PgBouncer charm didn't block as expected due to invalid extra user roles."
                        )
            except RetryError:
                if i >= 3:
                    raise
                logger.warning("The expected blocked message was not set")
                logger.info("Removing relation between charms")
                juju.remove_relation(f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB)
                juju.wait(lambda status: data_integrator_blocked(status), timeout=TIMEOUT)
                continue

            logger.info("Removing relation between charms")
            juju.remove_relation(f"{DATA_INTEGRATOR_APP_NAME}:{RELATION_ENDPOINT}", PGB)
            juju.wait(lambda status: data_integrator_blocked(status), timeout=TIMEOUT)
            break
