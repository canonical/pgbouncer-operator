#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import jubilant
import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_fixed

from . import architecture
from .helpers.helpers import CLIENT_APP_NAME
from .helpers.postgresql_helpers import get_leader_unit
from .jubilant_helpers import RoleAttributeValue


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


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Pytest fixture that wraps :meth:`jubilant.with_model`.

    This adds command line parameter ``--keep-models`` (see help for details).
    """
    controller = request.config.getoption("--controller")
    model = request.config.getoption("--model")
    controller_and_model = None
    if controller and model:
        controller_and_model = f"{controller}:{model}"
    elif controller:
        controller_and_model = controller
    elif model:
        controller_and_model = model
    keep_models = bool(request.config.getoption("--keep-models"))

    if controller_and_model:
        juju = jubilant.Juju(model=controller_and_model)  # type: ignore
        yield juju
        log = juju.debug_log(limit=1000)
    else:
        with jubilant.temp_model(keep=keep_models) as juju:
            yield juju
            log = juju.debug_log(limit=1000)

    if request.session.testsfailed:
        print(log, end="")


@pytest.fixture(scope="module")
def predefined_roles() -> dict:
    """Return a list of predefined roles with their expected permissions."""
    return {
        "": {
            "auto-escalate-to-database-owner": RoleAttributeValue.REQUESTED_DATABASE,
            "permissions": {
                "connect": RoleAttributeValue.REQUESTED_DATABASE,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.REQUESTED_DATABASE,
                "read-data": RoleAttributeValue.NO,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.NO,
            },
        },
        "charmed_stats": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.NO,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.NO,
            },
        },
        "charmed_read": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.ALL_DATABASES,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.NO,
            },
        },
        "charmed_dml": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.ALL_DATABASES,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.ALL_DATABASES,
            },
        },
        "charmed_backup": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.NO,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.YES,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.NO,
            },
        },
        "charmed_dba": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.ALL_DATABASES,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.YES,
                "write-data": RoleAttributeValue.ALL_DATABASES,
            },
        },
        "charmed_admin": {
            "auto-escalate-to-database-owner": RoleAttributeValue.ALL_DATABASES,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.NO,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.ALL_DATABASES,
                "read-data": RoleAttributeValue.ALL_DATABASES,
                "read-stats": RoleAttributeValue.ALL_DATABASES,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.NO,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.ALL_DATABASES,
            },
        },
        "CREATEDB": {
            "auto-escalate-to-database-owner": RoleAttributeValue.NO,
            "permissions": {
                "connect": RoleAttributeValue.ALL_DATABASES,
                "create-databases": RoleAttributeValue.YES,
                "create-objects": RoleAttributeValue.NO,
                "escalate-to-database-owner": RoleAttributeValue.NO,
                "read-data": RoleAttributeValue.NO,
                "read-stats": RoleAttributeValue.NO,
                "run-backup-commands": RoleAttributeValue.NO,
                "set-up-predefined-catalog-roles": RoleAttributeValue.YES,
                "set-user": RoleAttributeValue.NO,
                "write-data": RoleAttributeValue.NO,
            },
        },
    }


@pytest.fixture(scope="module")
def predefined_roles_combinations() -> list:
    """Return a list of valid combinations of predefined roles."""
    return [
        ("",),
        ("charmed_stats",),
        ("charmed_read",),
        ("charmed_dml",),
        ("charmed_admin",),
        ("charmed_admin", "CREATEDB"),
    ]
