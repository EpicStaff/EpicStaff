"""resolve_setting / require_setting / safe_error_message.

Each tool calls these with its own `globals()`, so tests build that dict
directly instead of loading a real tool module.
"""

import pytest

from epicstaff_common import require_setting, resolve_setting, safe_error_message


def test_resolve_setting_returns_the_present_value():
    assert resolve_setting({"db_uri": "postgresql://x"}, "db_uri") == "postgresql://x"


@pytest.mark.parametrize("falsy_value", [False, 0])
def test_resolve_setting_keeps_falsy_values_that_are_not_none(falsy_value):
    assert resolve_setting({"read_only": falsy_value}, "read_only", True) == falsy_value


def test_resolve_setting_falls_back_to_default_on_none():
    assert resolve_setting({"read_only": None}, "read_only", True) is True


def test_resolve_setting_falls_back_to_default_on_missing_key():
    assert resolve_setting({}, "read_only", True) is True


def test_resolve_setting_default_defaults_to_none():
    assert resolve_setting({}, "model") is None


def test_require_setting_returns_the_present_value():
    assert require_setting({"api_key": "sk-config"}, "api_key") == "sk-config"


@pytest.mark.parametrize("missing_globals", [{}, {"api_key": None}, {"api_key": ""}])
def test_require_setting_raises_when_blank(missing_globals):
    with pytest.raises(RuntimeError, match="api_key"):
        require_setting(missing_globals, "api_key")


def test_safe_error_message_returns_the_text_of_a_runtime_error_the_tool_raised():
    assert safe_error_message(RuntimeError("db_uri is required but not configured")) == (
        "db_uri is required but not configured"
    )


@pytest.mark.parametrize(
    "error",
    [
        ValueError("connection string: postgresql://user:secret@host/db"),
        ConnectionError("could not connect, key=sk-live-12345"),
    ],
)
def test_safe_error_message_never_returns_a_third_party_exceptions_text(error):
    message = safe_error_message(error)

    assert message == type(error).__name__
    assert "secret" not in message and "sk-live" not in message
