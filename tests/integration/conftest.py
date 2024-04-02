#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from .helpers.helpers import CLIENT_APP_NAME
from .helpers.postgresql_helpers import get_leader_unit


@pytest.fixture(scope="module")
async def pgb_charm_focal(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    return await ops_test.build_charm(".", bases_index=0)


@pytest.fixture(scope="module")
async def pgb_charm_jammy(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    return await ops_test.build_charm(".", bases_index=1)


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
