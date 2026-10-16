import pytest

from src.shared.envtools import Env, EnvironmentNotFoundError

# None of these tests touch the database, but tests/conftest.py has a session-scoped
# autouse `flush_test_db_once` fixture that calls `flush`. Without a test that pulls in
# the `db` fixture, pytest-django never swaps the connection to test_crew and that
# flush targets the real `crew` dev database. The marker forces proper test-database
# setup, matching every other module in this suite.
pytestmark = pytest.mark.django_db

PROBE = "EPICSTAFF_PROBE_BOOL"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("y", True),
        ("t", True),
        ("True", True),
        (" TRUE\n", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("n", False),
        ("f", False),
        ("False", False),
        ("  Off ", False),
    ],
)
def test_a_recognised_value_is_parsed(monkeypatch, value, expected):
    monkeypatch.setenv(PROBE, value)

    assert Env().bool(PROBE) is expected


@pytest.mark.parametrize(
    "value",
    ["flase", "ture", "enabled", "2", "", "   ", "none", "None"],
    ids=["typo-false", "typo-true", "word", "number", "empty", "whitespace", "none", "None"],
)
def test_an_unrecognised_value_fails_and_names_the_variable(monkeypatch, value):
    monkeypatch.setenv(PROBE, value)

    with pytest.raises(ValueError, match=f"{PROBE}=.*is not a boolean"):
        Env().bool(PROBE)


def test_an_unrecognised_value_fails_even_with_a_default(monkeypatch):
    monkeypatch.setenv(PROBE, "flase")

    with pytest.raises(ValueError, match=PROBE):
        Env().bool(PROBE, True)


def test_an_unset_variable_without_a_default_fails(monkeypatch):
    monkeypatch.delenv(PROBE, raising=False)

    with pytest.raises(EnvironmentNotFoundError, match=PROBE):
        Env().bool(PROBE)


@pytest.mark.parametrize("default", [True, False])
def test_an_unset_variable_returns_the_default(monkeypatch, default):
    monkeypatch.delenv(PROBE, raising=False)

    assert Env().bool(PROBE, default) is default
