"""Tests for app.logging_utils — redaction of payloads, messages and exceptions."""

from __future__ import annotations

import copy
import re

import pytest
from app import logging_utils
from app.logging_utils import (
    format_exception_for_log,
    redact,
    redact_messages,
    redact_payload,
    redact_value,
    summarize_validation_error,
)
from pydantic import BaseModel, ValidationError

_DIGEST_PATTERN = re.compile(r"^<redacted len=(\d+) digest=[0-9a-f]{12}>$")
_TEST_DIGEST_KEY = b"deterministic-test-key"

# Every substring pydantic adds to a rendered error that can echo the rejected input.
_PYDANTIC_LEAK_MARKERS = ("input_value", "input_type", "msg", "ctx", "url", "Input should")


@pytest.fixture
def fixed_digest_key(monkeypatch):
    monkeypatch.setattr(logging_utils, "_DIGEST_KEY", _TEST_DIGEST_KEY)


def test_redact_masks_nested_secrets():
    data = {
        "agents": [{"llm": {"config": {"api_key": "sk-secret", "model": "gpt-4o"}}}],
        "tools": [{"data": {"auth": "tok", "tool_name": "x"}}],
    }
    result = redact(data)

    assert result["agents"][0]["llm"]["config"]["api_key"] == "***"
    assert result["agents"][0]["llm"]["config"]["model"] == "gpt-4o"
    assert result["tools"][0]["data"]["auth"] == "***"
    assert result["tools"][0]["data"]["tool_name"] == "x"


def test_redact_preserves_non_secrets():
    data = {"name": "alice", "values": [1, 2, 3], "nested": {"count": 42}}
    result = redact(data)

    assert result == {"name": "alice", "values": [1, 2, 3], "nested": {"count": 42}}


def test_redact_none_secret_not_masked():
    data = {"api_key": None, "token": None, "name": "visible"}
    result = redact(data)

    assert result["api_key"] is None
    assert result["token"] is None
    assert result["name"] == "visible"


def test_redact_masks_storage_credentials():
    data = {
        "storage_credentials": {
            "access_key": "AKIAEXAMPLE",
            "secret_key": "super-secret-value",
            "endpoint": "http://minio:9000",
        },
        "storage_scope": "org-1",
    }
    result = redact(data)

    assert result["storage_credentials"]["access_key"] == "***"
    assert result["storage_credentials"]["secret_key"] == "***"
    assert result["storage_credentials"]["endpoint"] == "http://minio:9000"
    assert result["storage_scope"] == "org-1"


def test_redact_value_reports_length_and_digest_format():
    match = _DIGEST_PATTERN.match(redact_value("test"))

    assert match is not None
    assert match.group(1) == "4"


def test_redact_value_none():
    assert redact_value(None) == "<none>"


@pytest.mark.parametrize(
    "value",
    [
        "sk-live-abcdef",
        {"api_key": "sk-live-abcdef"},
        ["sk-live-abcdef"],
        123,
        b"sk-live-abcdef",
        ("sk-live-abcdef",),
    ],
)
def test_redact_value_never_leaks_the_value(value, fixed_digest_key):
    summary = redact_value(value)

    assert _DIGEST_PATTERN.match(summary) is not None
    assert str(value) not in summary


def test_redact_value_is_stable_for_equal_input():
    assert redact_value("secret") == redact_value("secret")
    assert redact_value("secret") != redact_value("secrez")


def test_redact_value_digest_depends_on_the_key(monkeypatch):
    with_one_key = redact_value("a longer piece of content")
    monkeypatch.setattr(logging_utils, "_DIGEST_KEY", _TEST_DIGEST_KEY)

    assert redact_value("a longer piece of content") != with_one_key


def test_redact_value_key_never_appears_in_output(fixed_digest_key):
    assert _TEST_DIGEST_KEY.decode() not in redact_value(_TEST_DIGEST_KEY.decode())


def test_redact_messages_redacts_content_and_tool_arguments():
    system_prompt = "You are a helpful agent for ACME."
    tool_arguments = '{"query": "patient record 42"}'
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": tool_arguments,
                    },
                }
            ],
        },
    ]

    result = redact_messages(messages)

    assert result[0]["content"] == redact_value(system_prompt)
    assert result[1]["content"] == "<none>"
    tool_call = result[1]["tool_calls"][0]
    assert tool_call["function"]["name"] == "search"
    assert tool_call["function"]["arguments"] == redact_value(tool_arguments)
    assert tool_arguments not in str(result)
    assert system_prompt not in str(result)


def test_redact_messages_digests_a_nested_dict_value():
    messages = [{"role": "user", "content": "hi", "headers": {"Authorization": "Bearer x"}}]

    result = redact_messages(messages)

    assert result[0]["headers"] == redact_value({"Authorization": "Bearer x"})
    assert "Bearer x" not in str(result)


def test_redact_messages_does_not_mutate_input():
    messages = [
        {
            "role": "assistant",
            "content": "original text",
            "tool_calls": [
                {"function": {"name": "search", "arguments": '{"query": "q"}'}}
            ],
        }
    ]
    snapshot = copy.deepcopy(messages)

    redact_messages(messages)

    assert messages == snapshot


def test_redact_messages_masks_an_unrecognized_key_by_default():
    sensitive_value = "patient record 42"
    messages = [{"role": "user", "content": "hi", "some_new_field": sensitive_value}]

    result = redact_messages(messages)

    assert result[0]["some_new_field"] == redact_value(sensitive_value)
    assert sensitive_value not in str(result)


def test_redact_messages_handles_multimodal_content_blocks():
    text_block = "describe this invoice"
    image_url = "https://x/secret.png"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_block},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    result = redact_messages(messages)

    assert isinstance(result[0]["content"], str)
    assert text_block not in result[0]["content"]
    assert image_url not in result[0]["content"]


def test_redact_messages_tool_call_id_type_pass_through():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"query": "secret_data"}',
                    },
                }
            ],
        }
    ]

    result = redact_messages(messages)

    tool_call = result[0]["tool_calls"][0]
    assert tool_call["id"] == "call_abc123"
    assert tool_call["type"] == "function"


def test_redact_messages_tool_call_unrecognized_key_masked():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "metadata": "internal tracking code",
                    "function": {
                        "name": "search",
                        "arguments": "{}",
                    },
                }
            ],
        }
    ]

    result = redact_messages(messages)

    tool_call = result[0]["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["type"] == "function"
    assert tool_call["metadata"] == redact_value("internal tracking code")
    assert "internal tracking code" not in str(result)


def test_redact_messages_message_not_a_dict_is_digested():
    sensitive_value = "patient record 42"
    messages = [sensitive_value]

    result = redact_messages(messages)

    assert result[0] == redact_value(sensitive_value)
    assert sensitive_value not in str(result)


def test_redact_messages_tool_calls_not_a_list_is_digested():
    sensitive_value = "patient record 42"
    messages = [{"role": "assistant", "content": None, "tool_calls": sensitive_value}]

    result = redact_messages(messages)

    assert result[0]["tool_calls"] == redact_value(sensitive_value)
    assert sensitive_value not in str(result)


def test_redact_messages_tool_call_entry_not_a_dict_is_digested():
    sensitive_value = "patient record 42"
    messages = [{"role": "assistant", "content": None, "tool_calls": [sensitive_value]}]

    result = redact_messages(messages)

    assert result[0]["tool_calls"][0] == redact_value(sensitive_value)
    assert sensitive_value not in str(result)


def test_redact_messages_tool_call_function_only_name_passes_through():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "role": "leaked-role",
                        "tool_call_id": "leaked-tcid",
                    },
                }
            ],
        }
    ]

    result = redact_messages(messages)

    function = result[0]["tool_calls"][0]["function"]
    assert function["name"] == "search"
    assert function["role"] == redact_value("leaked-role")
    assert function["tool_call_id"] == redact_value("leaked-tcid")
    assert "leaked-role" not in str(result)
    assert "leaked-tcid" not in str(result)


def test_redact_messages_tool_call_missing_function_is_digested_wholesale():
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]}]

    result = redact_messages(messages)

    assert result[0]["tool_calls"][0] == redact_value({"id": "call_1"})


def test_redact_messages_tool_call_function_not_a_dict_is_digested():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": '{"query": "secret"}'}
            ],
        }
    ]

    result = redact_messages(messages)

    tool_call = result[0]["tool_calls"][0]
    assert tool_call == redact_value(
        {"id": "call_1", "type": "function", "function": '{"query": "secret"}'}
    )
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    ("payload", "passthrough", "expected_kept", "expected_masked"),
    [
        (
            {"request_key": "sensitive data", "other": "data"},
            {"request_key"},
            ["request_key"],
            ["other"],
        ),
        (
            {"key1": "value1", "key2": "value2", "secret": "hidden"},
            {"key1", "key2"},
            ["key1", "key2"],
            ["secret"],
        ),
        (
            {"data": "sensitive", "info": "confidential"},
            set(),
            [],
            ["data", "info"],
        ),
        (
            {"key": None, "other": "data"},
            {"key"},
            ["key"],
            ["other"],
        ),
        (
            {"id": "req_123", "missing": None, "config": {"api_key": "sk-secret"}},
            {"id"},
            ["id"],
            ["missing", "config"],
        ),
        (
            {
                "id": "req_123",
                "config": {"api_key": "sk-secret", "debug": False},
                "data": [1, 2, 3],
            },
            {"id"},
            ["id"],
            ["config", "data"],
        ),
    ],
    ids=[
        "one_passthrough_key",
        "multiple_passthrough_keys",
        "empty_passthrough_masks_everything",
        "none_under_a_passthrough_key_stays_none",
        "none_under_a_masked_key_becomes_none_marker",
        "complex_values_are_digested",
    ],
)
def test_redact_payload_keeps_passthrough_keys_and_masks_the_rest(
    payload, passthrough, expected_kept, expected_masked
):
    result = redact_payload(payload, passthrough=passthrough)

    assert set(result) == set(payload)
    for key in expected_kept:
        assert result[key] == payload[key]
    for key in expected_masked:
        assert result[key] == redact_value(payload[key])
        if payload[key] is not None:
            assert str(payload[key]) not in result[key]


def test_redact_payload_does_not_mutate_input():
    payload = {"key": "value", "secret": "hidden"}
    snapshot = copy.deepcopy(payload)

    redact_payload(payload, passthrough={"key"})

    assert payload == snapshot


def test_redact_payload_non_dict_input_is_digested():
    sensitive_value = "not a dictionary"

    result = redact_payload(sensitive_value, passthrough={"key"})

    assert result == redact_value(sensitive_value)
    assert sensitive_value not in result


class _CodeTask(BaseModel):
    venv_id: str
    secrets: dict[str, str]
    storage_credentials: dict[str, str] | None = None


def _validation_error(**overrides) -> ValidationError:
    payload = {"venv_id": "venv-1", "secrets": {}}
    payload.update(overrides)
    with pytest.raises(ValidationError) as raised:
        _CodeTask(**payload)
    return raised.value


def test_summarize_validation_error_reports_type_and_location():
    error = _validation_error(secrets="sk-live-abcdef")

    summary = summarize_validation_error(error)

    assert summary.startswith("ValidationError:")
    assert "dict_type at secrets" in summary
    assert "1 error(s)" in summary


def test_summarize_validation_error_does_not_leak_the_rejected_input():
    secret_value = "sk-live-abcdef-super-secret"

    summary = summarize_validation_error(_validation_error(secrets=secret_value))

    assert secret_value not in summary
    assert "sk-live" not in summary


def test_summarize_validation_error_omits_pydantic_rendering_markers():
    summary = summarize_validation_error(
        _validation_error(secrets="sk-live-abcdef", storage_credentials=["not", "a", "dict"])
    )

    for marker in _PYDANTIC_LEAK_MARKERS:
        assert marker not in summary


def test_summarize_validation_error_reports_every_failure():
    summary = summarize_validation_error(
        _validation_error(venv_id=42, secrets="sk-live-abcdef")
    )

    assert "2 error(s)" in summary
    assert "at venv_id" in summary
    assert "at secrets" in summary


def test_summarize_validation_error_joins_a_nested_location():
    summary = summarize_validation_error(_validation_error(secrets={"OPENAI_API_KEY": 123}))

    assert "at secrets.OPENAI_API_KEY" in summary


def test_summarize_validation_error_locations_name_the_secret_key_not_its_value():
    """Accepted limitation: a dict field's key reaches the log, its value never does."""
    summary = summarize_validation_error(
        _validation_error(secrets={"OPENAI_API_KEY": ["sk-live-abcdef"]})
    )

    assert "OPENAI_API_KEY" in summary
    assert "sk-live-abcdef" not in summary


class _UnreadableValidationError(Exception):
    """Stands in for a validation error whose entries cannot be read."""

    def errors(self):
        raise RuntimeError("entries unavailable")

    def __str__(self):
        raise RuntimeError("str is broken too")


def test_summarize_validation_error_fails_closed_to_the_class_name():
    assert summarize_validation_error(_UnreadableValidationError()) == "_UnreadableValidationError"


class _EntriesMissingType(Exception):
    def errors(self):
        return [{"loc": ("secrets",), "input": "sk-live-abcdef"}]


def test_summarize_validation_error_fails_closed_when_an_entry_lacks_a_key():
    summary = summarize_validation_error(_EntriesMissingType())

    assert summary == "_EntriesMissingType"
    assert "sk-live-abcdef" not in summary


@pytest.mark.parametrize(
    ("error", "expected_class"),
    [
        (ValueError("secret-bearing message sk-live-abcdef"), "ValueError"),
        (KeyError("api_key"), "KeyError"),
        (RuntimeError(""), "RuntimeError"),
        (TimeoutError(), "TimeoutError"),
    ],
    ids=["value_error", "key_error", "empty_message", "no_message"],
)
def test_format_exception_for_log_is_the_class_name_and_a_digest(error, expected_class):
    assert format_exception_for_log(error) == f"{expected_class}: {redact_value(str(error))}"


def test_format_exception_for_log_digest_follows_the_class_name():
    formatted = format_exception_for_log(ValueError("sk-live-abcdef"))

    class_name, _, digest = formatted.partition(": ")
    assert class_name == "ValueError"
    assert _DIGEST_PATTERN.match(digest) is not None


def test_format_exception_for_log_does_not_leak_the_message():
    secret_value = "Bearer sk-live-abcdef"

    formatted = format_exception_for_log(RuntimeError(f"request failed: {secret_value}"))

    assert secret_value not in formatted
    assert "sk-live" not in formatted


def test_format_exception_for_log_carries_no_stack_frames():
    try:
        raise ValueError("sk-live-abcdef")
    except ValueError as error:
        formatted = format_exception_for_log(error)

    assert "Traceback" not in formatted
    assert __file__ not in formatted
    assert "line " not in formatted


class _BrokenStr(Exception):
    def __str__(self):
        raise RuntimeError("cannot stringify")


def test_format_exception_for_log_fails_closed_on_a_broken_str():
    assert format_exception_for_log(_BrokenStr()) == "_BrokenStr"


def test_format_exception_for_log_reports_a_validation_error_class():
    formatted = format_exception_for_log(_validation_error(secrets="sk-live-abcdef"))

    assert formatted.startswith("ValidationError: ")
    assert "sk-live-abcdef" not in formatted
    for marker in _PYDANTIC_LEAK_MARKERS:
        assert marker not in formatted
