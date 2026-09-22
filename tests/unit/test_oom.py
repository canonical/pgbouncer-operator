# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import subprocess
from unittest.mock import Mock, call

import pytest
from charms.operator_libs_linux.v2 import snap

import oom
from constants import SNAP_VITALITY_HINT

SNAP_NAME = "charmed-pgbouncer"


@pytest.fixture
def snap_commands(monkeypatch):
    commands = Mock()
    monkeypatch.setattr(oom.subprocess, "check_output", commands.read)
    monkeypatch.setattr(oom.subprocess, "check_call", commands.write)
    return commands


def config(hint):
    return json.dumps({"resilience": {"vitality-hint": hint}})


@pytest.mark.parametrize(
    "initial", [{}, {"resilience": {}}, {"resilience": {"vitality-hint": ""}}]
)
def test_missing_or_empty_hint(snap_commands, initial):
    snap_commands.read.side_effect = [json.dumps(initial), config(SNAP_NAME)]

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == -899

    assert snap_commands.mock_calls == [
        call.read(["/usr/bin/snap", "get", "system", "-d"], text=True),
        call.write(["/usr/bin/snap", "set", "system", f"{SNAP_VITALITY_HINT}={SNAP_NAME}"]),
        call.read(["/usr/bin/snap", "get", "system", "-d"], text=True),
    ]


@pytest.mark.parametrize(
    "hint",
    [
        "postgresql",
        "postgresql,charmed-postgresql",
        "charmed-pgbouncer-extra,postgresql,postgresql",
    ],
)
def test_append_preserves_exact_hint_and_order(snap_commands, hint):
    updated = f"{hint},{SNAP_NAME}"
    snap_commands.read.side_effect = [config(hint), config(updated)]

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == -900 + len(updated.split(","))

    snap_commands.write.assert_called_once_with([
        "/usr/bin/snap",
        "set",
        "system",
        f"{SNAP_VITALITY_HINT}={updated}",
    ])


@pytest.mark.parametrize(
    ("hint", "adjustment"),
    [
        (SNAP_NAME, -899),
        (f"{SNAP_NAME},postgresql", -899),
        (f"postgresql,{SNAP_NAME}", -898),
        (f"{SNAP_NAME},postgresql,{SNAP_NAME},other", -897),
    ],
)
def test_existing_hint_uses_last_rank_without_writing(snap_commands, hint, adjustment):
    snap_commands.read.return_value = config(hint)

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == adjustment
    assert oom.ensure_snap_oom_protection(SNAP_NAME) == adjustment

    assert snap_commands.read.call_count == 2
    snap_commands.write.assert_not_called()


def test_full_hint_with_existing_snap(snap_commands):
    snap_commands.read.return_value = config(
        ",".join([f"snap-{i}" for i in range(99)] + [SNAP_NAME])
    )

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == -800

    snap_commands.write.assert_not_called()


def test_append_last_available_entry(snap_commands):
    hint = ",".join(f"snap-{i}" for i in range(99))
    snap_commands.read.side_effect = [config(hint), config(f"{hint},{SNAP_NAME}")]

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == -800

    snap_commands.write.assert_called_once()


@pytest.mark.parametrize("size", [100, 101])
def test_full_hint_is_not_replaced(snap_commands, size):
    snap_commands.read.return_value = config(",".join(f"snap-{i}" for i in range(size)))

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_not_called()


@pytest.mark.parametrize(
    "document",
    [
        "not JSON",
        "[]",
        "null",
        "1",
        '{"resilience": []}',
        '{"resilience": null}',
        config(None),
        config([]),
        config({}),
        config(1),
        config(True),
    ],
)
def test_invalid_config_is_not_replaced(snap_commands, document):
    snap_commands.read.return_value = document

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_not_called()


@pytest.mark.parametrize(
    "error", [OSError("missing snap"), subprocess.CalledProcessError(1, "/usr/bin/snap")]
)
def test_read_failure_is_not_treated_as_absent(snap_commands, error):
    snap_commands.read.side_effect = error

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_not_called()


def test_write_failure_is_not_retried(snap_commands):
    snap_commands.read.return_value = config("postgresql")
    snap_commands.write.side_effect = subprocess.CalledProcessError(1, "/usr/bin/snap")

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_called_once()
    snap_commands.read.assert_called_once()


@pytest.mark.parametrize(
    "verified",
    [
        "",
        SNAP_NAME,
        f"other,postgresql,{SNAP_NAME}",
        "postgresql,other",
        f"postgresql,{SNAP_NAME}",
    ],
)
def test_failed_verification_does_not_overwrite_again(snap_commands, verified):
    snap_commands.read.side_effect = [config("postgresql,other"), config(verified)]

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_called_once()


def test_verification_read_failure_does_not_overwrite_again(snap_commands):
    snap_commands.read.side_effect = [config("postgresql"), OSError("read failed")]

    with pytest.raises(snap.SnapError):
        oom.ensure_snap_oom_protection(SNAP_NAME)

    snap_commands.write.assert_called_once()


def test_verification_returns_current_last_rank(snap_commands):
    snap_commands.read.side_effect = [
        config("postgresql"),
        config(f"postgresql,{SNAP_NAME},other,{SNAP_NAME}"),
    ]

    assert oom.ensure_snap_oom_protection(SNAP_NAME) == -896
