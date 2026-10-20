import pytest

from src.shared.envtools import Env, EnvironmentBlankError, EnvironmentNotFoundError

# None of these tests touch the database, but tests/conftest.py has a session-scoped
# autouse `flush_test_db_once` fixture that calls `flush`. Without a test that pulls in
# the `db` fixture, pytest-django never swaps the connection to test_crew and that
# flush targets the real `crew` dev database. The marker forces proper test-database
# setup, matching every other module in this suite.
pytestmark = pytest.mark.django_db

UNSET = object()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a-real-key", "a-real-key"),
        ("  a-real-key\n", "a-real-key"),
        (UNSET, EnvironmentNotFoundError),
        ("", EnvironmentBlankError),
        ("   ", EnvironmentBlankError),
    ],
    ids=["set", "padded", "unset", "empty", "whitespace"],
)
def test_a_required_secret_must_be_set_and_non_blank(monkeypatch, value, expected):
    if value is UNSET:
        monkeypatch.delenv("EPICSTAFF_PROBE_KEY", raising=False)
    else:
        monkeypatch.setenv("EPICSTAFF_PROBE_KEY", value)

    if isinstance(expected, type):
        with pytest.raises(expected, match="EPICSTAFF_PROBE_KEY"):
            Env().secret("EPICSTAFF_PROBE_KEY")
    else:
        assert Env().secret("EPICSTAFF_PROBE_KEY") == expected


def test_settings_expose_non_blank_signing_keys():
    from django.conf import settings

    assert settings.SECRET_KEY.strip()
    assert settings.SIMPLE_JWT["SIGNING_KEY"].strip()
