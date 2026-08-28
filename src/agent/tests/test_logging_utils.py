"""Tests for app.logging_utils — redact() and redacted_dump()."""

from __future__ import annotations

import copy

from app.logging_utils import redact, redacted_dump
from shared.models.agent_service import AgentRequest
from tests.test_contract import EXAMPLE_BLOB


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


def test_redacted_dump_masks_agent_request():
    blob = copy.deepcopy(EXAMPLE_BLOB)
    blob["agents"][0]["llm"]["config"]["api_key"] = "sk-real-secret"

    request = AgentRequest(correlation_id="x", **blob)
    dumped = redacted_dump(request)

    assert dumped["agents"][0]["llm"]["config"]["api_key"] == "***"
    assert dumped["agents"][0]["llm"]["config"]["model"] == "gpt-4o"
