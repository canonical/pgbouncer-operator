#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the PostgreSQL charm."""

import logging
from typing import Literal, Optional

from charms.data_platform_libs.v1.data_models import BaseConfigModel
from pydantic import Field, IPvAnyAddress

logger = logging.getLogger(__name__)


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    listen_port: int = Field(ge=0)
    metrics_port: int = Field(ge=0)
    vip: Optional[IPvAnyAddress]
    local_connection_type: Literal["tcp", "uds"]
    pool_mode: Literal["session", "transaction", "statement"]
    max_db_connections: int = Field(ge=0)
    max_prepared_statements: int = Field(ge=0, le=1000)
