#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from ...helpers.ha_helpers import get_unit_ip
from ...helpers.helpers import (
    PG,
    PGB,
)
from ...juju_ import juju_major_version
from .helpers import check_exposed_connection, fetch_action_get_credentials, DATA_INTEGRATOR_APP_NAME

logger = logging.getLogger(__name__)

HACLUSTER_NAME = "hacluster"

if juju_major_version < 3:
    tls_certificates_app_name = "tls-certificates-operator"
    tls_channel = "legacy/stable"
    tls_config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
else:
    tls_certificates_app_name = "self-signed-certificates"
    tls_channel = "latest/stable"
    tls_config = {"ca-common-name": "Test CA"}


@pytest.mark.abort_on_fail
async def test_deploy_and_relate(ops_test: OpsTest, charm):
    """Test basic functionality of database relation interface."""
    # Deploy both charms (multiple units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    config = {"database-name": "test-database"}
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=PGB,
                num_units=0,
            ),
            ops_test.model.deploy(
                PG,
                application_name=PG,
                num_units=2,
                channel="14/edge",
                config={"profile": "testing"},
            ),
            ops_test.model.deploy(
                DATA_INTEGRATOR_APP_NAME,
                channel="edge",
                num_units=3,
                config=config,
                series="jammy",
            ),
            ops_test.model.deploy(
                tls_certificates_app_name, config=tls_config, channel=tls_channel
            ),
            ops_test.model.deploy(
                HACLUSTER_NAME,
                channel="2.4/stable",
                num_units=0,
            ),
        )
        await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
        await ops_test.model.add_relation(f"{PGB}:ha", f"{HACLUSTER_NAME}:ha")
        await ops_test.model.add_relation(
            f"{DATA_INTEGRATOR_APP_NAME}:juju-info", f"{HACLUSTER_NAME}:juju-info"
        )

    await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1200)
    ip_addresses = [
        await get_unit_ip(ops_test, unit_name)
        for unit_name in ops_test.model.units
        if unit_name.startswith(DATA_INTEGRATOR_APP_NAME) or unit_name.startswith(PG)
    ]

    # Try to generate a vip
    base, last_octet = ip_addresses[0].rsplit(".", 1)
    last_octet = int(last_octet)
    global vip
    vip = None
    for _ in range(len(ip_addresses)):
        last_octet += 1
        if last_octet > 254:
            last_octet = 2
        addr = ".".join([base, str(last_octet)])
        if addr not in ip_addresses:
            vip = addr
            break
    logger.info(f"Setting VIP to {vip}")

    await ops_test.model.applications[PGB].set_config({"vip": vip})
    await ops_test.model.add_relation(PGB, DATA_INTEGRATOR_APP_NAME)
    await ops_test.model.wait_for_idle(status="active", timeout=600)

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)
    host, _ = credentials["postgresql"]["endpoints"].split(":")
    logger.info(f"Data integrator host is {host}")
    assert host == vip


async def test_add_tls(ops_test: OpsTest, charm):
    await ops_test.model.add_relation(PGB, tls_certificates_app_name)
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, True)


async def test_remove_tls(ops_test: OpsTest, charm):
    await ops_test.model.applications[PGB].remove_relation(
        f"{PGB}:certificates", f"{tls_certificates_app_name}:certificates"
    )
    await ops_test.model.wait_for_idle(status="active")

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    check_exposed_connection(credentials, False)


async def test_remove_vip(ops_test: OpsTest):
    async with ops_test.fast_forward():
        await ops_test.model.applications[PGB].reset_config(["vip"])
        await ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=300)
        assert (
            ops_test.model.applications[PGB].units[0].workload_status_message
            == "ha integration used without vip configuration"
        )

        await ops_test.model.applications[PGB].remove_relation(f"{PGB}:ha", f"{HACLUSTER_NAME}:ha")
        await ops_test.model.wait_for_idle(apps=[PGB], status="active", timeout=600)

    credentials = await fetch_action_get_credentials(
        ops_test.model.applications[DATA_INTEGRATOR_APP_NAME].units[0]
    )
    host, _ = credentials["postgresql"]["endpoints"].split(":")
    logger.info(f"Data integrator host is {host}")
    assert host != vip
