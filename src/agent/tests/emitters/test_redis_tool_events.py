"""
Tests for RedisStreamToolEventEmitter.

Verifies live agent.tool_call / agent.tool_result envelopes, name resolution,
truncation, token usage accumulation, and that live-publish failures never
propagate.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.emitters.redis_tool_events import RedisStreamToolEventEmitter
from app.llm.client import LLMChunk
from shared.models.agent_service import LoopResult, TokenUsage, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emitter() -> tuple[RedisStreamToolEventEmitter, list[dict]]:
    """Return (emitter, published_calls) where published_calls accumulates
    every dict passed to client.publish."""
    published: list[dict] = []

    client = MagicMock()

    async def capture_publish(stream: str, fields: dict) -> None:
        published.append(fields)

    client.publish = capture_publish

    emitter = RedisStreamToolEventEmitter(
        client=client,
        result_stream="agent.results",
        correlation_id="test-corr",
    )
    return emitter, published


def _decode_payload(fields: dict) -> dict:
    return json.loads(fields["payload"])


def _make_loop_result() -> LoopResult:
    return LoopResult(
        final_text="done",
        tool_invocations=1,
        iterations=1,
        stop_reason="completed",
        token_usage=TokenUsage(),
    )


# ---------------------------------------------------------------------------
# Live tool_call envelope
# ---------------------------------------------------------------------------


async def test_on_tool_call_publishes_live_envelope():
    emitter, published = _make_emitter()
    await emitter.on_tool_call(
        {"id": "call_1", "name": "search", "arguments": '{"q": "x"}'}
    )

    assert len(published) == 1
    assert published[0]["type"] == "agent.tool_call"
    assert published[0]["correlation_id"] == "test-corr"
    payload = _decode_payload(published[0])
    assert payload["id"] == "call_1"
    assert payload["name"] == "search"
    assert payload["arguments"] == '{"q": "x"}'
    assert payload["truncated"] is False
    assert payload["token_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert payload["task"] is None


async def test_on_task_start_labels_subsequent_live_tool_events():
    emitter, published = _make_emitter()
    await emitter.on_task_start("task_a", 0)
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result", is_error=False)
    )

    call_payload = _decode_payload(published[0])
    result_payload = _decode_payload(published[1])
    assert call_payload["task"] == {"name": "task_a", "order": 0}
    assert result_payload["task"] == {"name": "task_a", "order": 0}


async def test_on_tool_call_still_buffers_event():
    emitter, _ = _make_emitter()
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})

    assert len(emitter._buffered_events) == 1
    assert emitter._buffered_events[0]["event"] == "tool_call"


# ---------------------------------------------------------------------------
# Live tool_result envelope
# ---------------------------------------------------------------------------


async def test_on_tool_result_resolves_name_from_prior_call():
    emitter, published = _make_emitter()
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result text", is_error=False)
    )

    result_envelope = published[1]
    assert result_envelope["type"] == "agent.tool_result"
    payload = _decode_payload(result_envelope)
    assert payload["tool_call_id"] == "call_1"
    assert payload["name"] == "search"
    assert payload["content"] == "result text"
    assert payload["is_error"] is False
    assert payload["truncated"] is False


async def test_on_tool_result_without_prior_call_has_null_name():
    emitter, published = _make_emitter()
    await emitter.on_tool_result(
        ToolResult(tool_call_id="unknown_call", content="x", is_error=False)
    )

    payload = _decode_payload(published[0])
    assert payload["name"] is None


async def test_on_tool_result_still_buffers_event():
    emitter, _ = _make_emitter()
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result", is_error=False)
    )

    assert len(emitter._buffered_events) == 1
    assert emitter._buffered_events[0]["event"] == "tool_result"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


async def test_on_tool_call_truncates_long_arguments():
    emitter, published = _make_emitter()
    long_arguments = "x" * 3000
    await emitter.on_tool_call(
        {"id": "call_1", "name": "search", "arguments": long_arguments}
    )

    payload = _decode_payload(published[0])
    assert len(payload["arguments"]) == 2000
    assert payload["truncated"] is True


async def test_on_tool_result_truncates_long_content():
    emitter, published = _make_emitter()
    long_content = "y" * 3000
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content=long_content, is_error=False)
    )

    payload = _decode_payload(published[0])
    assert len(payload["content"]) == 2000
    assert payload["truncated"] is True


async def test_on_final_keeps_full_untruncated_content():
    emitter, published = _make_emitter()
    long_content = "y" * 3000
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content=long_content, is_error=False)
    )
    await emitter.on_final(_make_loop_result())

    final_payload = _decode_payload(published[-1])
    buffered_result = final_payload["events"][0]
    assert buffered_result["event"] == "tool_result"
    assert len(buffered_result["data"]["content"]) == 3000


# ---------------------------------------------------------------------------
# on_chunk publishes nothing live but accumulates usage
# ---------------------------------------------------------------------------


async def test_on_chunk_publishes_nothing_live():
    emitter, published = _make_emitter()
    await emitter.on_chunk(LLMChunk(delta_text="hello"))

    assert published == []


async def test_on_chunk_without_usage_leaves_totals_zero():
    emitter, published = _make_emitter()
    await emitter.on_chunk(LLMChunk(delta_text="hello"))
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})

    payload = _decode_payload(published[0])
    assert payload["token_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


async def test_token_usage_on_tool_call_is_delta_since_last_live_event():
    emitter, published = _make_emitter()
    await emitter.on_chunk(
        LLMChunk(
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})

    first_payload = _decode_payload(published[0])
    assert first_payload["token_usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }

    await emitter.on_chunk(
        LLMChunk(
            usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
        )
    )
    await emitter.on_tool_call({"id": "call_2", "name": "search", "arguments": "{}"})

    second_payload = _decode_payload(published[1])
    assert second_payload["token_usage"] == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
    }


async def test_token_usage_on_tool_result_immediately_after_tool_call_is_zero():
    emitter, published = _make_emitter()
    await emitter.on_chunk(
        LLMChunk(
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result", is_error=False)
    )

    tool_call_payload = _decode_payload(published[0])
    assert tool_call_payload["token_usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }

    tool_result_payload = _decode_payload(published[1])
    assert tool_result_payload["token_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


async def test_token_usage_delta_excludes_tokens_lost_to_failed_publish():
    client = MagicMock()
    published: list[dict] = []
    call_count = {"n": 0}

    async def flaky_publish(stream: str, fields: dict) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("redis unavailable")

        published.append(fields)

    client.publish = flaky_publish

    emitter = RedisStreamToolEventEmitter(
        client=client,
        result_stream="agent.results",
        correlation_id="test-corr",
    )

    # First live envelope's publish fails; its token delta (round 1) is
    # dropped from the stream, but the snapshot still advances so round 1
    # tokens are never re-emitted on the next event.
    await emitter.on_chunk(
        LLMChunk(
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})

    await emitter.on_chunk(
        LLMChunk(
            usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
        )
    )
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result", is_error=False)
    )

    assert len(published) == 1
    tool_result_payload = _decode_payload(published[0])
    assert tool_result_payload["token_usage"] == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
    }


# ---------------------------------------------------------------------------
# Full sequence and terminal payload parity with batch
# ---------------------------------------------------------------------------


async def test_full_sequence_terminal_payload_unchanged_by_live_events():
    emitter, published = _make_emitter()
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})
    await emitter.on_tool_result(
        ToolResult(tool_call_id="call_1", content="result", is_error=False)
    )
    await emitter.on_final(_make_loop_result())

    assert [fields["type"] for fields in published] == [
        "agent.tool_call",
        "agent.tool_result",
        "agent.result",
    ]
    final_payload = _decode_payload(published[-1])
    assert final_payload["final_text"] == "done"
    assert len(final_payload["events"]) == 2


# ---------------------------------------------------------------------------
# Live publish failures never propagate
# ---------------------------------------------------------------------------


async def test_live_publish_failure_does_not_propagate_and_buffering_continues():
    client = MagicMock()
    call_count = {"n": 0}

    async def flaky_publish(stream: str, fields: dict) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("redis unavailable")

    client.publish = flaky_publish

    emitter = RedisStreamToolEventEmitter(
        client=client,
        result_stream="agent.results",
        correlation_id="test-corr",
    )

    # First publish (live tool_call) raises internally but must not propagate.
    await emitter.on_tool_call({"id": "call_1", "name": "search", "arguments": "{}"})
    assert len(emitter._buffered_events) == 1

    await emitter.on_final(_make_loop_result())
    assert call_count["n"] == 2
