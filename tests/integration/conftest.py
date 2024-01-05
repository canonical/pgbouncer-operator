#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
@pytest.fixture(scope="module")
async def pgb_charm_focal(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    return await ops_test.build_charm(".", bases_index=0)


@pytest.mark.abort_on_fail
@pytest.fixture(scope="module")
async def pgb_charm_jammy(ops_test: OpsTest):
    """Build the pgbouncer charm."""
    return await ops_test.build_charm(".", bases_index=1)
