"""Tests for app.data_loader — payload redaction in DEBUG logs."""

from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock

import pytest
from app.data_loader import DataLoader
from shared.models.agent_service import AgentRequest
from shared.redis_streams import StreamEnvelope

from tests.log_capture import log_line_starting_with, capture_logs_at
from tests.test_contract import EXAMPLE_BLOB


@pytest.mark.asyncio
async def test_data_loader_redacts_payload_free_text_fields():
    """The task payload is an arbitrary dict; a free-text field like task_instructions
    must be digested, not printed, by the allowlist that covers it."""
    sensitive_marker = "SENSITIVE_TASK_INSTRUCTION_MARKER_12345"
    blob = copy.deepcopy(EXAMPLE_BLOB)
    blob["payload"]["task_instructions"] = sensitive_marker

    request = AgentRequest(correlation_id="test-corr-123", **blob)
    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="test-corr-123",
        payload={"request_key": "agent:request:xyz"},
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps(request.model_dump(exclude={"correlation_id"}))

    loader = DataLoader(host="localhost", port=6379)
    loader._client = mock_client

    with capture_logs_at("DEBUG") as logs:
        loaded_request = await loader.load(envelope)

    request_line = log_line_starting_with(logs, "AgentRequest correlation_id=")
    assert sensitive_marker not in request_line
    assert "test-corr-123" in request_line

    assert loaded_request.correlation_id == "test-corr-123"
    assert loaded_request.payload["task_instructions"] == sensitive_marker


@pytest.mark.asyncio
async def test_data_loader_redacts_agent_instructions():
    """The agent's system prompt is free text and must not reach the DEBUG log line."""
    sensitive_marker = "SENSITIVE_AGENT_INSTRUCTIONS_MARKER_67890"
    blob = copy.deepcopy(EXAMPLE_BLOB)
    blob["agents"][0]["instructions"] = sensitive_marker

    request = AgentRequest(correlation_id="test-corr-123", **blob)
    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="test-corr-123",
        payload={"request_key": "agent:request:xyz"},
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps(request.model_dump(exclude={"correlation_id"}))

    loader = DataLoader(host="localhost", port=6379)
    loader._client = mock_client

    with capture_logs_at("DEBUG") as logs:
        loaded_request = await loader.load(envelope)

    request_line = log_line_starting_with(logs, "AgentRequest correlation_id=")
    assert sensitive_marker not in request_line
    assert "<redacted" in request_line
    assert loaded_request.agents[0].name in request_line
    assert loaded_request.agents[0].instructions == sensitive_marker


@pytest.mark.asyncio
async def test_data_loader_redacts_python_code_tool_secrets():
    """A Python-code tool's resolved secrets are plaintext credentials; a key-name
    denylist does not know the key `secrets`, so they must be digested by default
    along with the rest of `tools` rather than passed through unmasked."""
    secret_value = "SENSITIVE_STRIPE_SECRET_KEY_24680"
    code_marker = "SENSITIVE_PYTHON_SOURCE_13579"
    blob = copy.deepcopy(EXAMPLE_BLOB)
    blob["tools"] = [
        {
            "unique_name": "python-code-tool:1",
            "data": {
                "id": 1,
                "name": "python-code-tool",
                "description": "Runs Python code.",
                "args_schema": {
                    "type": "object",
                    "title": "ArgumentsSchema",
                    "properties": {"x": {"type": "string"}},
                    "required": [],
                },
                "python_code": {
                    "code": code_marker,
                    "entrypoint": "run",
                    "global_kwargs": None,
                    "use_storage": False,
                    "storage_allowed_paths": None,
                    "storage_org_prefix": None,
                    "session_id": None,
                    "secrets": {"STRIPE_SK": secret_value},
                },
            },
        }
    ]

    request = AgentRequest(correlation_id="test-corr-123", **blob)
    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="test-corr-123",
        payload={"request_key": "agent:request:xyz"},
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps(request.model_dump(exclude={"correlation_id"}))

    loader = DataLoader(host="localhost", port=6379)
    loader._client = mock_client

    with capture_logs_at("DEBUG") as logs:
        loaded_request = await loader.load(envelope)

    request_line = log_line_starting_with(logs, "AgentRequest correlation_id=")
    assert secret_value not in request_line
    assert code_marker not in request_line
    assert "<redacted" in request_line
    assert loaded_request.tools[0].data.python_code.secrets["STRIPE_SK"] == secret_value


@pytest.mark.asyncio
async def test_data_loader_redacts_agent_llm_credentials():
    """An agent's resolved LLM config carries a plaintext provider api_key and any
    auth extra_headers; a blanket passthrough of `llm`/`fcm_llm` would leak both —
    on either field, since `fcm_llm` is the same `LLMData` shape as `llm`."""
    api_key_marker = "SENSITIVE_OPENAI_API_KEY_11223"
    header_marker = "SENSITIVE_BEARER_TOKEN_44556"
    fcm_api_key_marker = "SENSITIVE_FCM_API_KEY_77889"
    blob = copy.deepcopy(EXAMPLE_BLOB)
    blob["agents"][0]["llm"]["config"]["api_key"] = api_key_marker
    blob["agents"][0]["llm"]["config"]["extra_headers"] = {"Authorization": header_marker}
    blob["agents"][0]["fcm_llm"] = {
        "provider": "openai",
        "config": {"model": "gpt-4o-mini", "api_key": fcm_api_key_marker},
    }

    request = AgentRequest(correlation_id="test-corr-123", **blob)
    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="test-corr-123",
        payload={"request_key": "agent:request:xyz"},
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps(request.model_dump(exclude={"correlation_id"}))

    loader = DataLoader(host="localhost", port=6379)
    loader._client = mock_client

    with capture_logs_at("DEBUG") as logs:
        loaded_request = await loader.load(envelope)

    request_line = log_line_starting_with(logs, "AgentRequest correlation_id=")
    assert api_key_marker not in request_line
    assert header_marker not in request_line
    assert fcm_api_key_marker not in request_line
    assert "gpt-4o" in request_line
    assert "gpt-4o-mini" in request_line
    assert loaded_request.agents[0].llm.config.api_key == api_key_marker
