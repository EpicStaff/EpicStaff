"""Startup validation of the sandbox execution timeout settings.

Invariant: the sandbox refuses to start unless SANDBOX_DEFAULT_EXECUTION_TIMEOUT is a bounded
duration of at least MIN_EXECUTION_TIMEOUT seconds and not above SANDBOX_MAX_EXECUTION_TIMEOUT,
because a task without a timeout of its own runs under that default. SANDBOX_MAX_EXECUTION_TIMEOUT
may be none (no upper limit).

settings.py validates at import time, so each case reloads it under the patched environment.
It lives under chain_tests/ because that conftest supplies the environment settings.py needs.
"""

import importlib

import pytest

import settings


@pytest.fixture
def reload_settings_with_env():
    """Reload settings.py under patched variables, then restore the environment and module.

    A reload that raises leaves the module half re-executed, so the module is always reloaded
    again under the original environment afterwards; other tests share this module object.
    """
    environment = pytest.MonkeyPatch()

    def reload(**variables: str):
        for name, value in variables.items():
            environment.setenv(name, value)
        return importlib.reload(settings)

    yield reload

    environment.undo()
    importlib.reload(settings)


@pytest.mark.parametrize(
    ("max_timeout", "default_timeout"),
    [
        ("5m", "none"),
        ("5m", "2s"),
        ("5m", "10m"),
    ],
    ids=["default-none", "default-below-minimum", "default-above-maximum"],
)
def test_invalid_default_execution_timeout_refuses_startup(
    reload_settings_with_env, max_timeout, default_timeout
):
    with pytest.raises(ValueError, match="SANDBOX_DEFAULT_EXECUTION_TIMEOUT"):
        reload_settings_with_env(
            SANDBOX_MAX_EXECUTION_TIMEOUT=max_timeout,
            SANDBOX_DEFAULT_EXECUTION_TIMEOUT=default_timeout,
        )


def test_no_maximum_accepts_a_bounded_default(reload_settings_with_env):
    reloaded = reload_settings_with_env(
        SANDBOX_MAX_EXECUTION_TIMEOUT="none",
        SANDBOX_DEFAULT_EXECUTION_TIMEOUT="5m",
    )

    assert (reloaded.MAX_EXECUTION_TIMEOUT, reloaded.DEFAULT_EXECUTION_TIMEOUT) == (None, 300)
