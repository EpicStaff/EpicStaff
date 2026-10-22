"""Security flags in settings.py: only an explicit value is accepted, anything else fails startup.

Each test reloads the real settings module from the environment, so loosening the
parser settings.py uses (a typo reading as False and switching a protection off)
turns these red. The full value table of Env.bool lives with the other Env tests in
src/django_app/tests/settings_tests/test_env_bool.py.
"""

import importlib

import pytest
import settings

from src.shared.envtools import EnvironmentNotFoundError

UNSET = object()

FLAGS = [
    ("SANDBOX_MASK_SECRET", "MASK_SECRET"),
    ("SANDBOX_REQUIRE_ISOLATION", "REQUIRE_ISOLATION"),
]
VARIABLES = [variable for variable, _ in FLAGS]


@pytest.fixture
def load_settings(monkeypatch):
    """Reload settings with one variable set to a value, or removed for UNSET."""

    def load(variable, value):
        if value is UNSET:
            monkeypatch.delenv(variable, raising=False)
        else:
            monkeypatch.setenv(variable, value)
        return importlib.reload(settings)

    yield load
    # Restore the environment first, so the module every other test shares is rebuilt
    # from the suite's own values rather than from this test's.
    monkeypatch.undo()
    importlib.reload(settings)


@pytest.mark.parametrize(("variable", "attribute"), FLAGS)
@pytest.mark.parametrize(
    ("value", "expected"),
    [(" False ", False), ("0", False), ("true", True), ("ON", True)],
)
def test_an_explicit_value_sets_the_flag(load_settings, variable, attribute, value, expected):
    assert getattr(load_settings(variable, value), attribute) is expected


@pytest.mark.parametrize("variable", VARIABLES)
@pytest.mark.parametrize("value", ["flase", "", "none"], ids=["typo", "empty", "none"])
def test_an_unrecognised_value_fails_startup(load_settings, variable, value):
    with pytest.raises(ValueError, match=variable):
        load_settings(variable, value)


@pytest.mark.parametrize("variable", VARIABLES)
def test_startup_fails_when_the_variable_is_unset(load_settings, variable):
    with pytest.raises(EnvironmentNotFoundError, match=variable):
        load_settings(variable, UNSET)
