#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from asyncio import gather

import pytest
from pytest_operator.plugin import OpsTest

from constants import BACKEND_RELATION_NAME

from .helpers.helpers import (
    CLIENT_APP_NAME,
    FIRST_DATABASE_RELATION_NAME,
    PG,
    PGB,
    scale_application,
)

LS_CLIENT = "landscape-client"
UBUNTU_PRO_APP_NAME = "ubuntu-advantage"

logger = logging.getLogger(__name__)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest, pgb_charm_jammy, github_secrets):
    await gather(
        ops_test.model.deploy(
            pgb_charm_jammy,
            application_name=PGB,
            num_units=None,
            base="ubuntu@22.04",
        ),
        ops_test.model.deploy(
            PG,
            num_units=3,
            channel="14/edge",
        ),
        ops_test.model.deploy(
            CLIENT_APP_NAME,
            num_units=3,
            channel="latest/edge",
        ),
        ops_test.model.deploy(
            UBUNTU_PRO_APP_NAME,
            config={"token": github_secrets["UBUNTU_PRO_TOKEN"]},
            channel="latest/edge",
            num_units=0,
            base="ubuntu@22.04",
        ),
        ops_test.model.deploy(
            LS_CLIENT,
            config={
                "account-name": github_secrets["LANDSCAPE_ACCOUNT_NAME"],
                "registration-key": github_secrets["LANDSCAPE_REGISTRATION_KEY"],
                "ppa": "ppa:landscape/self-hosted-beta",
            },
            channel="latest/edge",
            num_units=0,
            base="ubuntu@22.04",
        ),
    )
    await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)

    await ops_test.model.wait_for_idle(
        apps=[CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=3000,
    )

    await ops_test.model.relate(f"{CLIENT_APP_NAME}:juju-info", f"{LS_CLIENT}:container")
    await ops_test.model.relate(f"{CLIENT_APP_NAME}:juju-info", f"{UBUNTU_PRO_APP_NAME}:juju-info")
    await ops_test.model.relate(f"{PG}:juju-info", f"{LS_CLIENT}:container")
    await ops_test.model.relate(f"{PG}:juju-info", f"{UBUNTU_PRO_APP_NAME}:juju-info")
    await ops_test.model.wait_for_idle(
        apps=[LS_CLIENT, UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB], status="active"
    )


@pytest.mark.group(1)
async def test_scale_up(ops_test: OpsTest, github_secrets):
    await scale_application(ops_test, CLIENT_APP_NAME, 4)

    await ops_test.model.wait_for_idle(
        apps=[LS_CLIENT, UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=1500,
    )


@pytest.mark.group(1)
async def test_scale_down(ops_test: OpsTest, github_secrets):
    await scale_application(ops_test, CLIENT_APP_NAME, 3)

    await ops_test.model.wait_for_idle(
        apps=[LS_CLIENT, UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=1500,
    )
