#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pydantic import ValidationError

from config import CharmConfig


def _base_config():
    return {
        "listen_port": 6432,
        "metrics_port": 9127,
        "vip": None,
        "local_connection_type": "tcp",
        "pool_mode": "session",
        "max_db_connections": 100,
        "max_prepared_statements": 100,
        "client_login_timeout": 60.0,
        "reserve_pool_timeout": 5.0,
        "server_idle_timeout": 600.0,
    }


def test_timeout_config_accepts_valid_values():
    config = CharmConfig(**{
        **_base_config(),
        "client_login_timeout": 0,
        "reserve_pool_timeout": 0,
        "server_idle_timeout": 0,
    })

    assert config.client_login_timeout == 0
    assert config.reserve_pool_timeout == 0
    assert config.server_idle_timeout == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("client_login_timeout", -1),
        ("reserve_pool_timeout", -1),
        ("server_idle_timeout", -1),
    ],
)
def test_timeout_config_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        CharmConfig(**{**_base_config(), field: value})
