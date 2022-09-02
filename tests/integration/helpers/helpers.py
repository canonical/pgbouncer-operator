#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import tempfile
import zipfile
from multiprocessing import ProcessError
from pathlib import Path
from typing import Dict

import yaml
from charms.pgbouncer_k8s.v0 import pgb
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from constants import AUTH_FILE_PATH, INI_PATH, LOG_PATH

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]
PG = "postgresql"


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


async def get_unit_cores(unit: str) -> int:
    """Get the number of CPU cores available on the given unit.

    Since PgBouncer is single-threaded, the charm automatically creates one instance of pgbouncer
    per CPU core on a given unit. Therefore, the number of cores is the expected number of
    pgbouncer instances.

    Args:
        unit: the juju unit instance

    Returns:
        The number of cores on the unit.
    """
    get_cores_from_unit = await unit.run("nproc --all")
    cores = get_cores_from_unit.results.get("Stdout")
    if cores is not None:
        return int(cores)
    else:
        raise Exception(get_cores_from_unit.results)


async def get_running_instances(unit: str, service: str) -> int:
    """Returns the number of running instances of the given service.

    Uses `ps` to find the number of instances of a given service.

    Args:
        unit: the juju unit running the service
        service: a string that can be used to grep for the intended service.

    Returns:
        an integer defining the number of running instances.
    """
    get_running_instances = await unit.run(f"ps aux | grep {service}")
    ps_output = get_running_instances.results.get("Stdout")
    num_of_ps_lines = len(ps_output.split("\n"))
    # one extra for grep process, and one for a blank line at the end
    return num_of_ps_lines - 2


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


async def get_cfg(ops_test: OpsTest, unit_name: str, path: str = INI_PATH) -> pgb.PgbConfig:
    """Gets pgbouncer config from unit filesystem."""
    cat = await cat_file_from_unit(ops_test, path, unit_name)
    return pgb.PgbConfig(cat)


async def get_pgb_log(ops_test: OpsTest, unit_name) -> str:
    """Gets pgbouncer logs from unit filesystem."""
    return await cat_file_from_unit(ops_test, LOG_PATH, unit_name)


async def get_userlist(ops_test: OpsTest, unit_name) -> str:
    """Gets pgbouncer logs from unit filesystem."""
    return await cat_file_from_unit(ops_test, AUTH_FILE_PATH, unit_name)


def get_backend_relation(ops_test: OpsTest):
    """Gets the backend-database relation used to connect pgbouncer to the backend."""
    app_name = ops_test.model.applications[PGB].name
    for rel in ops_test.model.relations:
        if app_name in rel.endpoints and "postgresql" in rel.endpoints:
            return rel

    return None


def get_legacy_relation_username(ops_test: OpsTest, relation_id: int):
    """Gets a username as it should be generated in the db and db-admin legacy relations."""
    app_name = ops_test.model.applications[PGB].name
    model_name = ops_test.model_name
    return f"{app_name}_user_{relation_id}_{model_name}".replace("-", "_")


async def get_backend_user_pass(ops_test, backend_relation):
    pgb_unit = ops_test.model.applications[PGB].units[0]
    backend_databag = await get_app_relation_databag(ops_test, pgb_unit.name, backend_relation.id)
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


async def deploy_postgres_bundle(ops_test: OpsTest, pg_config: dict = {}):
    """Build pgbouncer charm, deploy and relate it to postgresql charm.

    Returns:
        libjuju Relation object describing the relation between pgbouncer and postgres.
    """
    charm = await ops_test.build_charm(".")
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.deploy(
                charm,
                application_name=PGB,
            ),
            ops_test.model.deploy(
                PG,
                channel="edge",
                num_units=3,
                config=pg_config,
            ),
        )
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[PG], status="active", timeout=1000),
            ops_test.model.wait_for_idle(apps=[PGB], status="blocked", timeout=1000),
        )
        relation = await ops_test.model.add_relation(f"{PGB}:backend-database", f"{PG}:database")
        wait_for_relation_joined_between(ops_test, PG, PGB)
        await ops_test.model.wait_for_idle(apps=[PG, PGB], status="active", timeout=1000)

        return relation


async def deploy_and_relate_application_with_pgbouncer_bundle(
    ops_test: OpsTest,
    charm: str,
    application_name: str,
    number_of_units: int,
    config: dict = None,
    channel: str = "stable",
    relation: str = "db",
) -> int:
    """Helper function to deploy and relate application with Pgbouncer.

    Args:
        ops_test: The ops test framework.
        charm: Charm identifier.
        application_name: The name of the application to deploy.
        number_of_units: The number of units to deploy.
        config: Extra config options for the application.
        channel: The channel to use for the charm.
        relation: Name of the PostgreSQL relation to relate
            the application to.

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
    )
    await ops_test.model.wait_for_idle(
        apps=[application_name],
        status="active",
        raise_on_blocked=False,
        timeout=1000,
    )

    # Relate application to PostgreSQL.
    relation = await ops_test.model.relate(f"{application_name}", f"{PGB}:{relation}")
    await wait_for_relation_joined_between(ops_test, PGB, application_name)
    await ops_test.model.wait_for_idle(
        apps=[application_name, PG, PGB],
        status="active",
        raise_on_blocked=False,  # Application that needs a relation is blocked initially.
        timeout=1000,
    )

    return relation.id


async def deploy_and_relate_bundle_with_pgbouncer_bundle(
    ops_test: OpsTest, bundle: str, application_name: str, relation_name: str = "db"
) -> str:
    """Helper function to deploy and relate a bundle with pgbouncer.

    Assumes pgbouncer and postgres are deployed and related.

    Args:
        ops_test: The ops test framework.
        bundle: Bundle identifier.
        application_name: The name of the application to check for
            an active state after the deployment.
        relation_name: name of the relation to be added
    """
    # Deploy the bundle.
    with tempfile.NamedTemporaryFile() as original:
        # Download the original bundle.
        await ops_test.juju("download", bundle, "--filepath", original.name)

        # Open the bundle compressed file and update the contents
        # of the bundle.yaml file to deploy it.
        with zipfile.ZipFile(original.name, "r") as archive:
            bundle_yaml = archive.read("bundle.yaml")
            data = yaml.load(bundle_yaml, Loader=yaml.FullLoader)

            # Remove PostgreSQL and relations with it from the bundle.yaml file.
            del data["services"]["postgresql"]
            data["relations"] = [
                relation
                for relation in data["relations"]
                if "postgresql:db" not in relation and "postgresql:db-admin" not in relation
            ]

            # Write the new bundle content to a temporary file and deploy it.
            with tempfile.NamedTemporaryFile() as patched:
                patched.write(yaml.dump(data).encode("utf_8"))
                patched.seek(0)
                await ops_test.juju("deploy", patched.name)

    # Relate application to Pgbouncer.
    relation_name = await ops_test.model.relate(f"{application_name}", f"{PGB}:{relation_name}")
    await ops_test.model.wait_for_idle(
        apps=[application_name, PG, PGB],
        status="active",
        timeout=1000,
    )

    return relation_name.id
