#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
from multiprocessing import ProcessError
from pathlib import Path
from typing import Dict

import yaml
from charms.pgbouncer_k8s.v0 import pgb
from juju.unit import Unit
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from constants import AUTH_FILE_NAME, INI_NAME, PGB_CONF_DIR

CLIENT_APP_NAME = "postgresql-test-app"
FIRST_DATABASE_RELATION_NAME = "first-database"
SECOND_DATABASE_RELATION_NAME = "second-database"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"
WEEBL = "weebl"
MAILMAN3 = "mailman3-core"

WAIT_MSG = "waiting for backend database relation to connect"


def get_backend_relation(ops_test: OpsTest):
    """Gets the backend-database relation used to connect pgbouncer to the backend."""
    return get_joining_relations(ops_test, PGB, PG)[0]


def get_joining_relations(ops_test: OpsTest, app_1: str, app_2: str):
    """Gets every relation in this model that joins app_1 and app_2."""
    relations = []
    for rel in ops_test.model.relations:
        apps = [endpoint["application-name"] for endpoint in rel.data["endpoints"]]
        if app_1 in apps and app_2 in apps:
            relations.append(rel)
    return relations


async def get_unit_address(ops_test: OpsTest, application_name: str, unit_name: str) -> str:
    """Get unit IP address.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        unit_name: The name of the unit

    Returns:
        IP address of the unit
    """
    status = await ops_test.model.get_status()
    return status["applications"][application_name].units[unit_name]["address"]


async def get_unit_cores(ops_test: OpsTest, unit: Unit) -> int:
    """Get the number of CPU cores available on the given unit.

    Since PgBouncer is single-threaded, the charm automatically creates one instance of pgbouncer
    per CPU core on a given unit. Therefore, the number of cores is the expected number of
    pgbouncer instances.

    Args:
        ops_test: ops_test plugin
        unit: the juju unit instance

    Returns:
        The number of cores on the unit.
    """
    return int(await run_command_on_unit(ops_test, unit.name, "nproc --all"))


async def get_running_instances(ops_test: OpsTest, unit: Unit, service: str) -> int:
    """Returns the number of running instances of the given service.

    Uses `ps` to find the number of instances of a given service.

    Args:
        ops_test: ops_test plugin
        unit: the juju unit running the service
        service: a string that can be used to grep for the intended service.

    Returns:
        an integer defining the number of running instances.
    """
    get_running_instances = await run_command_on_unit(ops_test, unit.name, f"pgrep -cx {service}")
    return int(get_running_instances)


async def get_unit_info(ops_test: OpsTest, unit_name: str) -> Dict:
    """Gets the databags from the given relation.

    Args:
        ops_test: ops_test testing instance
        unit_name: name of the unit

    Returns:
        A dict containing all unit information available to juju
    """
    get_databag = await ops_test.juju(
        "show-unit",
        unit_name,
        "--format=json",
    )
    logging.info(get_databag)
    return json.loads(get_databag[1])[unit_name]


async def cat_file_from_unit(ops_test: OpsTest, filepath: str, unit_name: str) -> str:
    """Gets a file from the filesystem of a pgbouncer application unit."""
    cat_cmd = f"ssh {unit_name} sudo cat {filepath}"
    return_code, output, _ = await ops_test.juju(*cat_cmd.split(" "))
    if return_code != 0:
        raise ProcessError(
            "Expected cat command %s to succeed instead it failed: %s %s %s",
            cat_cmd,
            return_code,
            output,
            _,
        )
    return output


async def get_cfg(ops_test: OpsTest, unit_name: str, path: str = None) -> pgb.PgbConfig:
    """Gets pgbouncer config from unit filesystem."""
    if path is None:
        app_name = unit_name.split("/")[0]
        path = f"{PGB_CONF_DIR}/{app_name}/{INI_NAME}"
    cat = await cat_file_from_unit(ops_test, path, unit_name)
    return pgb.PgbConfig(cat)


async def get_auth_file(ops_test: OpsTest, unit_name) -> str:
    """Gets pgbouncer auth file from unit filesystem."""
    app_name = unit_name.split("/")[0]
    return await cat_file_from_unit(
        ops_test, f"{PGB_CONF_DIR}/{app_name}/{AUTH_FILE_NAME}", unit_name
    )


async def run_sql(ops_test, unit_name, command, pgpass, user, host, port, dbname):
    run_cmd = f"exec --unit {unit_name} --"
    connstr = f"--username={user} -h {host} -p {port} --dbname={dbname}"
    cmd = f'PGPASSWORD={pgpass} psql {connstr} --command="{command}"'
    return await ops_test.juju(*run_cmd.split(" "), cmd)


def get_legacy_relation_username(ops_test: OpsTest, relation_id: int):
    """Gets a username as it should be generated in the db and db-admin legacy relations."""
    app_name = ops_test.model.applications[PGB].name
    model_name = ops_test.model_name
    return f"{app_name}_user_{relation_id}_{model_name}".replace("-", "_")


async def get_juju_secret(ops_test: OpsTest, secret_uri: str) -> Dict[str, str]:
    """Retrieve juju secret."""
    secret_unique_id = secret_uri.split("/")[-1]
    complete_command = f"show-secret {secret_uri} --reveal --format=json"
    _, stdout, _ = await ops_test.juju(*complete_command.split())
    return json.loads(stdout)[secret_unique_id]["content"]["Data"]


async def get_backend_user_pass(ops_test, backend_relation):
    pgb_unit = ops_test.model.applications[PGB].units[0]
    backend_databag = await get_app_relation_databag(ops_test, pgb_unit.name, backend_relation.id)
    if secret_uri := backend_databag.get("secret-user"):
        secret_data = await get_juju_secret(ops_test, secret_uri)
        return (secret_data["username"], secret_data["password"])

    pgb_user = backend_databag["username"]
    pgb_password = backend_databag["password"]
    return (pgb_user, pgb_password)


async def get_app_relation_databag(ops_test: OpsTest, unit_name: str, relation_id: int) -> Dict:
    """Gets the app relation databag from the given relation.

    Juju show-unit command is backwards, so you have to pass the unit_name of the unit to which the
    data is presented, not the unit that presented the data.

    Args:
        ops_test: ops_test testing instance
        unit_name: name of the unit to which this databag is presented
        relation_id: id of the required relation

    Returns:
        App databag for the relation with the given ID, or None if nothing can be found.
    """
    unit_data = await get_unit_info(ops_test, unit_name)
    relations = unit_data["relation-info"]
    for relation in relations:
        if relation["relation-id"] == relation_id:
            return relation.get("application-data", None)

    return None


def wait_for_relation_joined_between(
    ops_test: OpsTest, endpoint_one: str, endpoint_two: str
) -> None:
    """Wait for relation to be be created before checking if it's waiting or idle.

    Args:
        ops_test: running OpsTest instance
        endpoint_one: one endpoint of the relation. Doesn't matter if it's provider or requirer.
        endpoint_two: the other endpoint of the relation.
    """
    try:
        for attempt in Retrying(stop=stop_after_delay(3 * 60), wait=wait_fixed(3)):
            with attempt:
                if new_relation_joined(ops_test, endpoint_one, endpoint_two):
                    break
    except RetryError:
        assert False, "New relation failed to join after 3 minutes."


def new_relation_joined(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    for rel in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in rel.endpoints]
        if endpoint_one in endpoints and endpoint_two in endpoints:
            return True
    return False


def wait_for_relation_removed_between(
    ops_test: OpsTest, endpoint_one: str, endpoint_two: str
) -> None:
    """Wait for relation to be removed before checking if it's waiting or idle.

    Args:
        ops_test: running OpsTest instance
        endpoint_one: one endpoint of the relation. Doesn't matter if it's provider or requirer.
        endpoint_two: the other endpoint of the relation.
    """
    try:
        for attempt in Retrying(stop=stop_after_delay(3 * 60), wait=wait_fixed(3)):
            with attempt:
                if relation_exited(ops_test, endpoint_one, endpoint_two):
                    break
    except RetryError:
        assert False, "Relation failed to exit after 3 minutes."


def relation_exited(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    """Returns true if the relation between endpoint_one and endpoint_two has been removed."""
    for rel in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in rel.endpoints]
        if endpoint_one not in endpoints and endpoint_two not in endpoints:
            return True
    return False


async def deploy_postgres_bundle(
    ops_test: OpsTest,
    pgb_charm,
    pgb_config: dict = {},
    pgb_series: str = "jammy",
    pg_config: dict = {},
    db_units=3,
):
    """Build pgbouncer charm, deploy and relate it to postgresql charm.

    Returns:
        libjuju Relation object describing the relation between pgbouncer and postgres.
    """
    await asyncio.gather(
        ops_test.model.deploy(
            pgb_charm,
            application_name=PGB,
            config=pgb_config,
            num_units=None,
            series=pgb_series,
        ),
        ops_test.model.deploy(
            PG,
            channel="14/edge",
            num_units=db_units,
            config=pg_config,
        ),
    )
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[PG], status="active", timeout=1000, wait_for_exact_units=db_units
        )
        relation = await ops_test.model.add_relation(f"{PGB}:backend-database", f"{PG}:database")
        await ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=600)

    return relation


async def deploy_and_relate_application_with_pgbouncer_bundle(
    ops_test: OpsTest,
    charm: str,
    application_name: str,
    number_of_units: int = 1,
    config: dict = {},
    channel: str = "stable",
    relation: str = "db",
    series: str = "jammy",
    force: bool = False,
    wait: bool = True,
):
    """Helper function to deploy and relate application with Pgbouncer cluster.

    This assumes pgbouncer already exists and is related to postgres

    Args:
        ops_test: The ops test framework.
        charm: Charm identifier.
        application_name: The name of the application to deploy.
        number_of_units: The number of units to deploy.
        config: Extra config options for the application.
        channel: The channel to use for the charm.
        relation: Name of the pgbouncer relation to relate
            the application to.
        series: The series on which to deploy.
        force: Allow charm to be deployed to a machine running an unsupported series.
        wait: Wait for model to idle

    Returns:
        the id of the created relation.
    """
    # Deploy application.
    await ops_test.model.deploy(
        charm,
        channel=channel,
        application_name=application_name,
        num_units=number_of_units,
        config=config,
        series=series,
        force=force,
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[application_name],
            timeout=600,
        )

    # Relate application to pgbouncer.
    relation = await ops_test.model.relate(application_name, f"{PGB}:{relation}")
    wait_for_relation_joined_between(ops_test, PGB, application_name)
    if wait:
        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[application_name, PG, PGB],
                status="active",
                timeout=600,
            )

    return relation


async def scale_application(ops_test: OpsTest, application_name: str, count: int) -> None:
    """Scale a given application to a specific unit count.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        count: The desired number of units to scale to
    """
    change = count - len(ops_test.model.applications[application_name].units)
    if change > 0:
        await ops_test.model.applications[application_name].add_units(change)
    elif change < 0:
        units = [
            unit.name for unit in ops_test.model.applications[application_name].units[0:-change]
        ]
        await ops_test.model.applications[application_name].destroy_units(*units)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[application_name], status="active", timeout=1000, wait_for_exact_units=count
        )


async def run_command_on_unit(ops_test: OpsTest, unit_name: str, command: str) -> str:
    """Run a command on a specific unit.

    Args:
        ops_test: The ops test framework instance
        unit_name: The name of the unit to run the command on
        command: The command to run

    Returns:
        the command output if it succeeds, otherwise raises an exception.
    """
    complete_command = ["exec", "--unit", unit_name, "--", *command.split()]
    return_code, stdout, _ = await ops_test.juju(*complete_command)
    if return_code != 0:
        raise Exception(
            "Expected command %s to succeed instead it failed: %s", command, return_code
        )
    return stdout
