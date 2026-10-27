"""Tests for app.logging_utils — redact(), redact_value(), redact_messages(), redact_payload()."""

from __future__ import annotations

import copy
import re

import pytest
from app import logging_utils
from app.logging_utils import redact, redact_messages, redact_payload, redact_value

_DIGEST_PATTERN = re.compile(r"^<redacted len=(\d+) digest=[0-9a-f]{12}>$")
_TEST_DIGEST_KEY = b"deterministic-test-key"


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
