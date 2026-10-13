"""Pure os.environ manipulation — no containers, no DB, no sandbox."""

import json

import pytest

from src.shared.epicstaff_secrets import SecretNotAvailableError, get_secret
from src.shared.epicstaff_secrets import secrets as lib

ENV_VAR = "EPICSTAFF_SECRETS"

# These tests never touch the ORM. But tests/conftest.py has an autouse
# `heal_builtin_roles` fixture that queries the Role table before every db test, and
# without a test that pulls in the `db` fixture, pytest-django never swaps the
# connection to the test database, so that query would hit the real dev database.
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    # The parsed payload is cached after first read, so every test starts fresh.
    lib.clear_cache()
    monkeypatch.delenv(ENV_VAR, raising=False)
    yield
    lib.clear_cache()


def test_a_declared_secret_is_returned_and_cached_after_the_first_read(monkeypatch):
    monkeypatch.setenv(ENV_VAR, json.dumps({"K": "first"}))
    assert get_secret("K") == "first"

    monkeypatch.setenv(ENV_VAR, json.dumps({"K": "second"}))
    assert get_secret("K") == "first"


@pytest.mark.parametrize(
    "declared",
    [None, {}, {"STRIPE_KEY": "sk-live-abc", "SLACK_TOKEN": "xoxb-1"}],
    ids=["env-unset", "node-declared-nothing", "typo"],
)
def test_an_undeclared_secret_names_what_is_available_but_never_a_value(monkeypatch, declared):
    if declared is not None:
        monkeypatch.setenv(ENV_VAR, json.dumps(declared))

    with pytest.raises(SecretNotAvailableError) as exc:
        get_secret("TYPO")

    message = str(exc.value)
    assert "TYPO" in message
    # wrap_code prints str(e) to stderr; a KeyError would wrap it in quotes.
    assert not message.startswith(("'", '"'))
    for name, value in (declared or {}).items():
        assert name in message
        # A value in an error message ends up in stderr and the PythonCodeResult row.
        assert value not in message
