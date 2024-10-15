# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from typing import Dict, Optional, Tuple

import psycopg2
import requests
from pytest_operator.plugin import OpsTest
from tenacity import (
    Retrying,
    stop_after_delay,
    wait_fixed,
)

from .helpers import CLIENT_APP_NAME
from .postgresql_helpers import get_leader_unit

logger = logging.getLogger(__name__)


class ProcessError(Exception):
    """Raised when a process fails."""


async def are_writes_increasing(
    ops_test, down_unit: Optional[str] = None, use_ip_from_inside: bool = False
) -> None:
    """Verify new writes are continuing by counting the number of writes."""
    writes, _ = await count_writes(
        ops_test, down_unit=down_unit, use_ip_from_inside=use_ip_from_inside
    )
    for member, count in writes.items():
        for attempt in Retrying(stop=stop_after_delay(60 * 3), wait=wait_fixed(3)):
            with attempt:
                more_writes, _ = await count_writes(
                    ops_test, down_unit=down_unit, use_ip_from_inside=use_ip_from_inside
                )
                assert more_writes[member] > count, f"{member}: writes not continuing to DB"


def get_patroni_cluster(unit_ip: str) -> Dict[str, str]:
    resp = requests.get(f"http://{unit_ip}:8008/cluster")
    return resp.json()


async def check_writes(ops_test, use_ip_from_inside: bool = False) -> int:
    """Gets the total writes from the test charm and compares to the writes from db."""
    total_expected_writes = await stop_continuous_writes(ops_test)
    actual_writes, max_number_written = await count_writes(
        ops_test, use_ip_from_inside=use_ip_from_inside
    )
    for member, count in actual_writes.items():
        assert (
            count == max_number_written[member]
        ), f"{member}: writes to the db were missed: count of actual writes different from the max number written."
        assert total_expected_writes == count, f"{member}: writes to the db were missed."
    return total_expected_writes


async def count_writes(
    ops_test: OpsTest, down_unit: Optional[str] = None, use_ip_from_inside: bool = False
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Count the number of writes in the database."""
    app = "postgresql"
    password = await get_password(ops_test, app, down_unit)
    for unit in ops_test.model.applications[app].units:
        if unit.name != down_unit:
            cluster = get_patroni_cluster(
                await (
                    get_ip_from_inside_the_unit(ops_test, unit.name)
                    if use_ip_from_inside
                    else get_unit_ip(ops_test, unit.name)
                )
            )
            break
    down_ips = []
    if down_unit:
        for unit in ops_test.model.applications[app].units:
            if unit.name == down_unit:
                down_ips.append(unit.public_address)
                down_ips.append(await get_unit_ip(ops_test, unit.name))
    count = {}
    maximum = {}
    for member in cluster["members"]:
        if member["role"] != "replica" and member["host"] not in down_ips:
            host = member["host"]

            connection_string = (
                f"dbname='{CLIENT_APP_NAME.replace('-', '_')}_database' user='operator'"
                f" host='{host}' password='{password}' connect_timeout=10"
            )

            with psycopg2.connect(connection_string) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(number), MAX(number) FROM continuous_writes;")
                results = cursor.fetchone()
                count[member["name"]] = results[0]
                maximum[member["name"]] = results[1]
            connection.close()
    return count, maximum


async def get_ip_from_inside_the_unit(ops_test: OpsTest, unit_name: str) -> str:
    command = f"exec --unit {unit_name} -- hostname -I"
    return_code, stdout, stderr = await ops_test.juju(*command.split())
    if return_code != 0:
        raise ProcessError(
            "Expected command %s to succeed instead it failed: %s %s", command, return_code, stderr
        )
    return stdout.splitlines()[0].strip()


async def get_password(ops_test: OpsTest, app: str, down_unit: Optional[str] = None) -> str:
    """Use the charm action to retrieve the password from provided application.

    Returns:
        string with the password stored on the peer relation databag.
    """
    # Can retrieve from any unit running unit, so we pick the first.
    for unit in ops_test.model.applications[app].units:
        if unit.name != down_unit:
            unit_name = unit.name
            break
    action = await ops_test.model.units.get(unit_name).run_action("get-password")
    action = await action.wait()
    return action.results["password"]


async def get_unit_ip(ops_test: OpsTest, unit_name: str) -> str:
    """Wrapper for getting unit ip.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to get the address
    Returns:
        The (str) ip of the unit
    """
    application = unit_name.split("/")[0]
    for unit in ops_test.model.applications[application].units:
        if unit.name == unit_name:
            break
    return await instance_ip(ops_test, unit.machine.hostname)


async def instance_ip(ops_test: OpsTest, instance: str) -> str:
    """Translate juju instance name to IP.

    Args:
        ops_test: pytest ops test helper
        instance: The name of the instance

    Returns:
        The (str) IP address of the instance
    """
    _, output, _ = await ops_test.juju("machines")

    for line in output.splitlines():
        if instance in line:
            return line.split()[2]


async def start_continuous_writes(ops_test: OpsTest, app: str) -> None:
    """Start continuous writes to PostgreSQL."""
    # Start the process by relating the application to the database or
    # by calling the action if the relation already exists.
    relations = [
        relation
        for relation in ops_test.model.applications[app].relations
        if not relation.is_peer
        and f"{relation.requires.application_name}:{relation.requires.name}"
        == f"{CLIENT_APP_NAME}:database"
    ]
    if not relations:
        await ops_test.model.relate(app, f"{CLIENT_APP_NAME}:database")
        await ops_test.model.wait_for_idle(status="active", timeout=1000)
    for attempt in Retrying(stop=stop_after_delay(60 * 5), wait=wait_fixed(3), reraise=True):
        with attempt:
            leader = await get_leader_unit(ops_test, CLIENT_APP_NAME)
            action = await leader.run_action("start-continuous-writes")
            await action.wait()
            assert action.results["result"] == "True", "Unable to create continuous_writes table"


async def stop_continuous_writes(ops_test: OpsTest) -> int:
    """Stops continuous writes to PostgreSQL and returns the last written value."""
    leader = await get_leader_unit(ops_test, CLIENT_APP_NAME)
    action = await leader.run_action("stop-continuous-writes")
    action = await action.wait()
    return int(action.results["writes"])
