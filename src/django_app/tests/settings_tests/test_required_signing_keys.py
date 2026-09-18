import pytest
from django.core.exceptions import ImproperlyConfigured

from django_app.settings import _require_env

# None of these tests touch the database, but tests/conftest.py has a session-scoped
# autouse `flush_test_db_once` fixture that calls `flush`. Without a test that pulls in
# the `db` fixture, pytest-django never swaps the connection to test_crew and that
# flush targets the real `crew` dev database. The marker forces proper test-database
# setup, matching every other module in this suite.
pytestmark = pytest.mark.django_db


def test_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("EPICSTAFF_PROBE_KEY", "a-real-key")

    assert _require_env("EPICSTAFF_PROBE_KEY") == "a-real-key"


def test_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("EPICSTAFF_PROBE_KEY", "  a-real-key\n")

    assert _require_env("EPICSTAFF_PROBE_KEY") == "a-real-key"


def test_raises_when_unset(monkeypatch):
    monkeypatch.delenv("EPICSTAFF_PROBE_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured, match="EPICSTAFF_PROBE_KEY"):
        _require_env("EPICSTAFF_PROBE_KEY")


def test_raises_when_empty(monkeypatch):
    monkeypatch.setenv("EPICSTAFF_PROBE_KEY", "")

    with pytest.raises(ImproperlyConfigured, match="EPICSTAFF_PROBE_KEY"):
        _require_env("EPICSTAFF_PROBE_KEY")


def test_raises_when_whitespace_only(monkeypatch):
    monkeypatch.setenv("EPICSTAFF_PROBE_KEY", "   ")

    with pytest.raises(ImproperlyConfigured, match="EPICSTAFF_PROBE_KEY"):
        _require_env("EPICSTAFF_PROBE_KEY")


def test_settings_expose_non_blank_signing_keys():
    from django.conf import settings

    assert settings.SECRET_KEY.strip()
    assert settings.SIMPLE_JWT["SIGNING_KEY"].strip()
