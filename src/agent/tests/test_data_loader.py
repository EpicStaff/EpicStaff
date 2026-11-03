"""Tests for app.data_loader — payload redaction in DEBUG logs."""

from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.data_loader import DataLoader
from app.exceptions import DataLoadError
from app.request_handler import RequestHandler
from shared.models.agent_service import AgentRequest
from shared.redis_streams import StreamEnvelope

from tests.log_capture import assert_masked_exception, log_line_starting_with, capture_logs_at
from tests.test_contract import EXAMPLE_BLOB

_ENVELOPE = StreamEnvelope(
    type="agent.run",
    correlation_id="test-corr-123",
    payload={"request_key": "agent:request:xyz"},
)


def _wire_blob(**overrides) -> dict:
    """The JSON blob as crew writes it: a dump of a valid request, then overridden."""
    valid_request = AgentRequest(correlation_id="test-corr-123", **copy.deepcopy(EXAMPLE_BLOB))
    dumped = valid_request.model_dump(exclude={"correlation_id"}, mode="json")
    dumped.update(overrides)
    return dumped


def _loader_returning(raw: str) -> DataLoader:
    mock_client = AsyncMock()
    mock_client.get.return_value = raw
    loader = DataLoader(host="localhost", port=6379)
    loader._client = mock_client
    return loader


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


@pytest.mark.asyncio
async def test_validation_failure_logs_types_and_locations_without_rejected_values():
    """A rejected value reaches pydantic's own rendering verbatim, so the ERROR line
    must carry only the failure type and its location."""
    rejected_marker = "SENSITIVE_RUN_TYPE_MARKER_31415"
    blob = _wire_blob(run_type=rejected_marker)

    loader = _loader_returning(json.dumps(blob))

    with capture_logs_at("ERROR") as logs:
        with pytest.raises(DataLoadError):
            await loader.load(_ENVELOPE)

    error_line = log_line_starting_with(logs, "failed to parse AgentRequest key=")
    assert rejected_marker not in error_line
    assert "key=agent:request:xyz" in error_line
    assert "ValidationError" in error_line
    assert "1 error(s)" in error_line
    assert "at run_type" in error_line


@pytest.mark.asyncio
async def test_non_validation_failure_logs_class_name_and_digest_only():
    """A blob that is valid JSON but not an object fails before pydantic runs; the
    ERROR line names the exception class and digests its message."""
    loader = _loader_returning(json.dumps(["not", "an", "object"]))

    with capture_logs_at("ERROR") as logs:
        with pytest.raises(DataLoadError):
            await loader.load(_ENVELOPE)

    error_line = log_line_starting_with(logs, "failed to parse AgentRequest key=")
    assert_masked_exception(error_line, "TypeError")


@pytest.mark.asyncio
async def test_validation_failure_raises_unchanged_data_load_error_text():
    """The exception text crew consumes still carries pydantic's full detail — only the
    log line is redacted."""
    rejected_marker = "SENSITIVE_RUN_TYPE_MARKER_27182"
    blob = _wire_blob(run_type=rejected_marker)

    loader = _loader_returning(json.dumps(blob))

    with pytest.raises(DataLoadError) as raised:
        await loader.load(_ENVELOPE)

    message = str(raised.value)
    assert message.startswith("Failed to parse AgentRequest from key 'agent:request:xyz': ")
    assert rejected_marker in message
    assert isinstance(raised.value.__cause__, ValidationError)


@pytest.mark.asyncio
async def test_validation_failure_publishes_unchanged_error_payload_to_crew():
    """The ``agent.error`` payload crew reads is the raw ``DataLoadError`` text,
    unaffected by the redacted log line."""
    rejected_marker = "SENSITIVE_RUN_TYPE_MARKER_16180"
    blob = _wire_blob(run_type=rejected_marker)

    with pytest.raises(DataLoadError) as raised:
        await _loader_returning(json.dumps(blob)).load(_ENVELOPE)
    expected_error_text = str(raised.value)

    publish_calls: list[dict] = []

    async def record_publish(stream, fields, maxlen=1_000_000, approximate=True, ttl_s=None):
        publish_calls.append({"stream": stream, "fields": fields})

    redis_client = MagicMock()
    redis_client.publish = record_publish
    redis_client.ack = AsyncMock(return_value=1)

    handler = RequestHandler(
        loader=_loader_returning(json.dumps(blob)),
        factory=MagicMock(),
        redis_client=redis_client,
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
        request_stream="agent.requests",
        consumer_group="agent-executors",
    )

    await handler.handle(_ENVELOPE, message_id="1-0", stream="agent.requests")

    assert len(publish_calls) == 1
    assert publish_calls[0]["fields"]["type"] == "agent.error"
    published = json.loads(publish_calls[0]["fields"]["payload"])
    assert published["error"] == expected_error_text
    assert rejected_marker in published["error"]


@pytest.mark.asyncio
async def test_withdrawal_check_failure_logs_class_name_and_digest_only():
    """A RedisError message can quote the connection string, credentials included;
    the WARNING line names the class and digests the message."""
    secret_marker = "SENSITIVE_REDIS_PASSWORD_MARKER_57721"
    loader = DataLoader(host="localhost", port=6379)
    loader._client = AsyncMock()
    loader._client.exists.side_effect = RedisError(f"auth failed for {secret_marker}")

    with capture_logs_at("WARNING") as logs:
        withdrawn = await loader.is_withdrawn(_ENVELOPE)

    warning_line = log_line_starting_with(logs, "withdrawal check failed key=")
    assert secret_marker not in warning_line
    assert "key=agent:request:xyz" in warning_line
    assert_masked_exception(warning_line, "RedisError")
    assert withdrawn is False
