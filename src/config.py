#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the PostgreSQL charm."""

import logging
from typing import Literal

from charms.data_platform_libs.v1.data_models import BaseConfigModel
from pydantic import Field, IPvAnyAddress

logger = logging.getLogger(__name__)


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    listen_port: int | None = Field(ge=1, default=6432)
    metrics_port: int | None = Field(ge=1, default=9127)
    vip: IPvAnyAddress | None = Field(default=None)
    local_connection_type: Literal["tcp", "uds"] = Field(default="tcp")
    pool_mode: Literal["session", "transaction", "statement"] = Field(default="session")
    max_db_connections: int | None = Field(ge=0, default=100)
