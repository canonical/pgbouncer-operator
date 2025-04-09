#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
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


@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest, charm):
    await gather(
        ops_test.model.deploy(
            charm,
            application_name=PGB,
            num_units=0,
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
            config={"token": os.environ["UBUNTU_PRO_TOKEN"]},
            channel="latest/edge",
            num_units=0,
            # TODO switch back to series when pylib juju can figure out the base:
            # https://github.com/juju/python-libjuju/issues/1240
            series="jammy",
        ),
    )
    await ops_test.model.add_relation(f"{PGB}:{BACKEND_RELATION_NAME}", f"{PG}:database")
    await ops_test.model.add_relation(f"{CLIENT_APP_NAME}:{FIRST_DATABASE_RELATION_NAME}", PGB)

    await ops_test.model.wait_for_idle(
        apps=[CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=3000,
    )

    # TODO re-add landscape client
    await ops_test.model.relate(f"{CLIENT_APP_NAME}:juju-info", f"{UBUNTU_PRO_APP_NAME}:juju-info")
    await ops_test.model.relate(f"{PG}:juju-info", f"{UBUNTU_PRO_APP_NAME}:juju-info")
    await ops_test.model.wait_for_idle(
        apps=[UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB], status="active"
    )


async def test_scale_up(ops_test: OpsTest):
    await scale_application(ops_test, CLIENT_APP_NAME, 4)

    await ops_test.model.wait_for_idle(
        apps=[UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=1500,
    )


async def test_scale_down(ops_test: OpsTest):
    await scale_application(ops_test, CLIENT_APP_NAME, 3)

    await ops_test.model.wait_for_idle(
        apps=[UBUNTU_PRO_APP_NAME, CLIENT_APP_NAME, PG, PGB],
        status="active",
        timeout=1500,
    )
