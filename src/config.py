#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the PostgreSQL charm."""

import logging
from typing import Literal, Optional

from charms.data_platform_libs.v0.data_models import BaseConfigModel
from pydantic import IPvAnyAddress, PositiveInt, confloat, conint

logger = logging.getLogger(__name__)


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    listen_port: PositiveInt
    metrics_port: PositiveInt
    vip: Optional[IPvAnyAddress]
    local_connection_type: Literal["tcp", "uds"]
    pool_mode: Literal["session", "transaction", "statement"]
    max_db_connections: conint(ge=0)
    max_prepared_statements: conint(ge=0, le=1000)
    client_login_timeout: confloat(ge=0)
    reserve_pool_timeout: confloat(ge=0)
    server_idle_timeout: confloat(ge=0)
