#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from . import architecture
from .helpers.helpers import CLIENT_APP_NAME
from .helpers.postgresql_helpers import get_leader_unit


@pytest.fixture(scope="session")
def charm():
    # Return str instead of pathlib.Path since python-libjuju's model.deploy(), juju deploy, and
    # juju bundle files expect local charms to begin with `./` or `/` to distinguish them from
    # Charmhub charms.
    return f"./pgbouncer_ubuntu@22.04-{architecture.architecture}.charm"


@pytest.fixture(scope="session")
def charm_noble():
    # Return str instead of pathlib.Path since python-libjuju's model.deploy(), juju deploy, and
    # juju bundle files expect local charms to begin with `./` or `/` to distinguish them from
    # Charmhub charms.
    return f"./pgbouncer_ubuntu@24.04-{architecture.architecture}.charm"


@pytest.fixture(scope="session")
def charm_focal(charm):
    # Workaround for basic multi-base testing
    # For better multi-base testing (e.g. running the same test on multiple bases), use
    # mysql-router-operator as an example
    return charm.replace("22.04", "20.04")


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
