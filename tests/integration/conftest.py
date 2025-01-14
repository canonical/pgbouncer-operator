#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import pathlib

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from . import architecture
from .helpers.helpers import CLIENT_APP_NAME
from .helpers.postgresql_helpers import get_leader_unit


@pytest.fixture(scope="module")
def pgb_charm_focal(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    if architecture.architecture == "amd64":
        # python-libjuju's model.deploy(), juju deploy, and juju bundle files expect local charms
        # to begin with `./` or `/` to distinguish them from Charmhub charms.
        # Therefore, we need to return an absolute path—a relative `pathlib.Path` does not start
        # with `./` when cast to a str.
        # (python-libjuju model.deploy() expects a str but will cast any input to a str as a
        # workaround for pytest-operator's non-compliant `build_charm` return type of
        # `pathlib.Path`.)
        return pathlib.Path("pgbouncer_ubuntu@20.04-amd64.charm").resolve(strict=True)
    elif architecture.architecture == "arm64":
        return pathlib.Path("pgbouncer_ubuntu@20.04-arm64.charm").resolve(strict=True)
    else:
        raise ValueError(architecture.architecture)


@pytest.fixture(scope="module")
async def pgb_charm_jammy(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    return await ops_test.build_charm(".")


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest) -> None:
    """Cleans up continuous writes after a test run."""
    yield
    # Clear the written data at the end.
    for attempt in Retrying(stop=stop_after_delay(60 * 5), wait=wait_fixed(3), reraise=True):
        with attempt:
            leader = await get_leader_unit(ops_test, CLIENT_APP_NAME)
            action = await leader.run_action("clear-continuous-writes")
            await action.wait()
            assert action.results["result"] == "True", "Unable to clear up continuous_writes table"
