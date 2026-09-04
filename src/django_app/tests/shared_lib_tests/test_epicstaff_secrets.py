"""Pure os.environ manipulation — no containers, no DB, no sandbox."""

import json

import pytest

from src.shared.epicstaff_secrets import secrets as lib

ENV_VAR = "EPICSTAFF_SECRETS"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    # The parsed payload is cached after first read, so every test starts fresh.
    lib.clear_cache()
    monkeypatch.delenv(ENV_VAR, raising=False)
    yield
    lib.clear_cache()


def test_returns_the_declared_value(monkeypatch):
    monkeypatch.setenv(ENV_VAR, json.dumps({"STRIPE_KEY": "sk-live-abc"}))

    assert lib.get_secret("STRIPE_KEY") == "sk-live-abc"


def test_undeclared_name_raises_and_lists_what_is_available(monkeypatch):
    monkeypatch.setenv(
        ENV_VAR, json.dumps({"STRIPE_KEY": "sk-live-abc", "SLACK_TOKEN": "xoxb-1"})
    )

    with pytest.raises(lib.SecretNotAvailableError) as exc:
        lib.get_secret("TYPO")

    message = str(exc.value)
    assert "TYPO" in message
    assert "STRIPE_KEY" in message
    assert "SLACK_TOKEN" in message
    # Names only. A value in an error message ends up in stderr and in the
    # PythonCodeResult row.
    assert "sk-live-abc" not in message
    assert "xoxb-1" not in message


def test_unset_env_raises_with_an_empty_available_list():
    with pytest.raises(lib.SecretNotAvailableError) as exc:
        lib.get_secret("ANYTHING")

    assert "ANYTHING" in str(exc.value)


def test_node_declared_nothing():
    # Same error as a typo, empty available list — the node declared no secrets.
    import os

    os.environ[ENV_VAR] = json.dumps({})
    try:
        with pytest.raises(lib.SecretNotAvailableError):
            lib.get_secret("ANYTHING")
    finally:
        del os.environ[ENV_VAR]


def test_value_is_cached_after_first_read(monkeypatch):
    monkeypatch.setenv(ENV_VAR, json.dumps({"K": "first"}))
    assert lib.get_secret("K") == "first"

    monkeypatch.setenv(ENV_VAR, json.dumps({"K": "second"}))
    assert lib.get_secret("K") == "first"


def test_error_is_not_a_keyerror_subclass():
    """str(KeyError) wraps its message in quotes. wrap_code prints str(e) to
    stderr, so a KeyError base would give the user a quoted, harder-to-read
    message."""
    assert not issubclass(lib.SecretNotAvailableError, KeyError)


def test_public_api_is_importable_from_the_package():
    from src.shared.epicstaff_secrets import SecretNotAvailableError, get_secret

    assert callable(get_secret)
    assert issubclass(SecretNotAvailableError, Exception)
