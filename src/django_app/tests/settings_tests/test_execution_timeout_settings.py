"""The execution timeout settings django_app derives from the sandbox environment.

Invariant: SANDBOX_EXECUTION_TIMEOUT becomes the maximum in whole seconds, rounded down so a
stored timeout never exceeds what the sandbox enforces (none means no maximum), and
SANDBOX_DEFAULT_EXECUTION_TIMEOUT becomes the default. A default below the minimum or above
the maximum stops django_app from starting, because every new PythonCode would get a
timeout its own validation rejects; so does a default of none.
"""

import importlib
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

import django_app.settings.execution_timeout as execution_timeout_settings
from django_app.settings import env

VARIABLES = ("SANDBOX_EXECUTION_TIMEOUT", "SANDBOX_DEFAULT_EXECUTION_TIMEOUT")


@pytest.fixture
def load_settings() -> Iterator[Callable[[str, str], ModuleType]]:
    """Re-run the settings module against the given environment values.

    The module computes its values at import, from the `env` the settings package read
    once, so the test edits that `env` and reloads the module. The original values are
    put back and the module reloaded again, so later tests see the real settings.
    """
    original = {name: env._envs.get(name) for name in VARIABLES}

    def _load(max_value: str, default_value: str) -> ModuleType:
        env._envs["SANDBOX_EXECUTION_TIMEOUT"] = max_value
        env._envs["SANDBOX_DEFAULT_EXECUTION_TIMEOUT"] = default_value
        return importlib.reload(execution_timeout_settings)

    yield _load

    for name, value in original.items():
        if value is None:
            env._envs.pop(name, None)
        else:
            env._envs[name] = value
    importlib.reload(execution_timeout_settings)


@pytest.mark.parametrize(
    ("max_value", "default_value", "expected_max", "expected_default"),
    [
        ("5m", "5m", 300, 300),
        ("10m", "90s", 600, 90),
        ("90.9s", "90s", 90, 90),
        ("none", "1h", None, 3600),
        ("5m", "3s", 300, 3),
    ],
    ids=[
        "default-equals-maximum",
        "default-below-maximum",
        "fractional-maximum-rounds-down",
        "no-maximum",
        "default-at-minimum",
    ],
)
def test_valid_configuration(
    load_settings, max_value, default_value, expected_max, expected_default
):
    module = load_settings(max_value, default_value)

    assert module.MIN_EXECUTION_TIMEOUT_SECONDS == 3
    assert module.MAX_EXECUTION_TIMEOUT_SECONDS == expected_max
    assert module.DEFAULT_EXECUTION_TIMEOUT_SECONDS == expected_default


@pytest.mark.parametrize(
    ("max_value", "default_value"),
    [("5m", "2s"), ("5m", "6m"), ("2s", "2s")],
    ids=[
        "default-below-minimum",
        "default-above-maximum",
        "maximum-below-minimum",
    ],
)
def test_invalid_configuration_stops_startup(load_settings, max_value, default_value):
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_DEFAULT_EXECUTION_TIMEOUT must be"):
        load_settings(max_value, default_value)


@pytest.mark.parametrize("max_value", ["5m", "none"], ids=["with-maximum", "no-maximum"])
def test_no_default_stops_startup(load_settings, max_value):
    with pytest.raises(
        ImproperlyConfigured, match="SANDBOX_DEFAULT_EXECUTION_TIMEOUT cannot be none"
    ):
        load_settings(max_value, "none")
