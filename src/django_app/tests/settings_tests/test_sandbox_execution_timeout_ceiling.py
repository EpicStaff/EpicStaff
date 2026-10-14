"""The largest node execution timeout is derived from SANDBOX_EXECUTION_TIMEOUT.

Invariant: node timeouts are whole minutes and must never exceed what the sandbox
enforces, so the ceiling is SANDBOX_EXECUTION_TIMEOUT rounded down to whole minutes.
A value that leaves no valid node timeout (`none`, or less than one minute) stops
django_app from starting instead of producing a ceiling of 0 or unlimited.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_app.settings.sandbox import max_execution_timeout_minutes
from src.shared.envtools import Env

ENVIRONMENT_VARIABLE = "SANDBOX_EXECUTION_TIMEOUT_UNDER_TEST"


def _ceiling_for(raw_value: str, monkeypatch) -> int:
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, raw_value)
    return max_execution_timeout_minutes(Env().time(ENVIRONMENT_VARIABLE))


@pytest.mark.parametrize(
    ("raw_value", "expected_minutes"),
    [
        ("5m", 5),
        ("60s", 1),
        ("1m", 1),
        ("119s", 1),
        ("330s", 5),
        ("2h", 120),
    ],
)
def test_ceiling_is_the_timeout_rounded_down_to_whole_minutes(
    raw_value, expected_minutes, monkeypatch
):
    assert _ceiling_for(raw_value, monkeypatch) == expected_minutes


@pytest.mark.parametrize("raw_value", ["none", "59s", "1s"])
def test_value_leaving_no_valid_node_timeout_stops_startup(raw_value, monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_EXECUTION_TIMEOUT"):
        _ceiling_for(raw_value, monkeypatch)
