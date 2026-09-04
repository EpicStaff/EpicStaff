"""
Tests for RedisStreamBatchEmitter.

Verifies warning buffering/deduplication and that both on_final and on_error
publish a payload containing a 'warnings' key.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.emitters.redis_batch import RedisStreamBatchEmitter
from shared.models.agent_service import LoopResult, TaskRunSummary, TokenUsage
from shared.redis_streams import StreamEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emitter() -> tuple[RedisStreamBatchEmitter, list[dict]]:
    """Return (emitter, published_calls) where published_calls accumulates
    every dict passed to client.publish."""
    published: list[dict] = []

    client = MagicMock()

    async def capture_publish(stream: str, fields: dict) -> None:
        published.append(fields)

    client.publish = capture_publish

    emitter = RedisStreamBatchEmitter(
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
        tool_invocations=0,
        iterations=1,
        stop_reason="completed",
        token_usage=TokenUsage(),
    )


# ---------------------------------------------------------------------------
# on_warning buffering and deduplication
# ---------------------------------------------------------------------------


async def test_on_warning_buffers_message():
    emitter, _ = _make_emitter()
    await emitter.on_warning("context near limit")
    assert emitter._warnings == ["context near limit"]


async def test_on_warning_deduplicates_identical_messages():
    emitter, _ = _make_emitter()
    await emitter.on_warning("same warning")
    await emitter.on_warning("same warning")
    await emitter.on_warning("same warning")
    assert emitter._warnings == ["same warning"]


async def test_on_warning_keeps_distinct_messages():
    emitter, _ = _make_emitter()
    await emitter.on_warning("warning A")
    await emitter.on_warning("warning B")
    assert emitter._warnings == ["warning A", "warning B"]


# ---------------------------------------------------------------------------
# on_final includes warnings in published payload
# ---------------------------------------------------------------------------


async def test_on_final_includes_warnings_key_when_no_warnings():
    emitter, published = _make_emitter()
    await emitter.on_final(_make_loop_result())

    assert len(published) == 1
    payload = _decode_payload(published[0])
    assert "warnings" in payload
    assert payload["warnings"] == []


async def test_on_final_includes_warnings_after_on_warning():
    emitter, published = _make_emitter()
    await emitter.on_warning("approaching limit")
    await emitter.on_final(_make_loop_result())

    payload = _decode_payload(published[0])
    assert payload["warnings"] == ["approaching limit"]


async def test_on_final_deduped_warnings_in_payload():
    emitter, published = _make_emitter()
    await emitter.on_warning("dup")
    await emitter.on_warning("dup")
    await emitter.on_final(_make_loop_result())

    payload = _decode_payload(published[0])
    assert payload["warnings"] == ["dup"]


# ---------------------------------------------------------------------------
# on_error includes warnings in published payload
# ---------------------------------------------------------------------------


async def test_on_error_includes_warnings_key_when_no_warnings():
    emitter, published = _make_emitter()
    await emitter.on_error(RuntimeError("boom"))

    assert len(published) == 1
    payload = _decode_payload(published[0])
    assert "warnings" in payload
    assert payload["warnings"] == []


async def test_on_error_includes_warnings_after_on_warning():
    emitter, published = _make_emitter()
    await emitter.on_warning("context limit warning")
    await emitter.on_error(RuntimeError("something failed"))

    payload = _decode_payload(published[0])
    assert payload["warnings"] == ["context limit warning"]


# ---------------------------------------------------------------------------
# on_final serializes per-task summaries
# ---------------------------------------------------------------------------


async def test_on_final_tasks_is_none_for_single_task_result():
    emitter, published = _make_emitter()
    await emitter.on_final(_make_loop_result())

    payload = _decode_payload(published[0])
    assert payload["tasks"] is None


async def test_on_final_serializes_populated_task_summaries():
    emitter, published = _make_emitter()
    result = LoopResult(
        final_text="B done",
        tool_invocations=3,
        iterations=5,
        stop_reason="completed",
        token_usage=TokenUsage(prompt_tokens=7, completion_tokens=5, total_tokens=12),
        tasks=[
            TaskRunSummary(
                name="task_a",
                order=0,
                final_text="A done",
                token_usage=TokenUsage(
                    prompt_tokens=2,
                    completion_tokens=1,
                    total_tokens=3,
                    cached_prompt_tokens=1,
                ),
                iterations=2,
                tool_invocations=1,
                stop_reason="completed",
            ),
            TaskRunSummary(
                name="task_b",
                order=1,
                final_text="B done",
                token_usage=TokenUsage(
                    prompt_tokens=5,
                    completion_tokens=4,
                    total_tokens=9,
                    cached_prompt_tokens=2,
                ),
                iterations=3,
                tool_invocations=2,
                stop_reason="completed",
            ),
        ],
    )

    await emitter.on_final(result)

    payload = _decode_payload(published[0])
    assert payload["tasks"] == [
        {
            "name": "task_a",
            "order": 0,
            "final_text": "A done",
            "structured_output": None,
            "token_usage": {
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "total_tokens": 3,
                "cached_prompt_tokens": 1,
                "total_cost_usd": 0.0,
            },
            "iterations": 2,
            "tool_invocations": 1,
            "stop_reason": "completed",
        },
        {
            "name": "task_b",
            "order": 1,
            "final_text": "B done",
            "structured_output": None,
            "token_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 4,
                "total_tokens": 9,
                "cached_prompt_tokens": 2,
                "total_cost_usd": 0.0,
            },
            "iterations": 3,
            "tool_invocations": 2,
            "stop_reason": "completed",
        },
    ]


# ---------------------------------------------------------------------------
# on_final includes structured_output in published payload
# ---------------------------------------------------------------------------


async def test_on_final_includes_structured_output_when_schema_enforced():
    emitter, published = _make_emitter()
    result = LoopResult(
        final_text='{"a": 1}',
        structured_output={"a": 1},
        tool_invocations=0,
        iterations=1,
        stop_reason="schema_satisfied",
        token_usage=TokenUsage(),
    )

    await emitter.on_final(result)

    payload = _decode_payload(published[0])
    assert payload["structured_output"] == {"a": 1}


async def test_on_final_structured_output_is_none_without_schema():
    emitter, published = _make_emitter()
    await emitter.on_final(_make_loop_result())

    payload = _decode_payload(published[0])
    assert payload["structured_output"] is None
