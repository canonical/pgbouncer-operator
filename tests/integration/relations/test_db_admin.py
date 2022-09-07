#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import ast
import json
import logging
from pathlib import Path

import pytest
import yaml
from landscape_api.base import run_query
from pytest_operator.plugin import OpsTest

from tests.integration.helpers.helpers import (
    deploy_and_relate_bundle_with_pgbouncer_bundle,
    deploy_postgres_bundle,
    get_backend_user_pass,
    get_legacy_relation_username,
)
from tests.integration.helpers.postgresql_helpers import (
    check_database_users_existence,
    check_databases_creation,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PGB = METADATA["name"]


# TODO write test with telegraf operator
