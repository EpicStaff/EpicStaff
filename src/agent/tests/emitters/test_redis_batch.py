"""
Tests for RedisStreamBatchEmitter.

Verifies warning buffering/deduplication and that both on_final and on_error
publish a payload containing a 'warnings' key.
"""

from __future__ import annotations

import pytest

import json
from unittest.mock import MagicMock

from app.emitters.redis_batch import RedisStreamBatchEmitter
from shared.models.agent_service import LoopResult, TaskRunSummary, TokenUsage
from tests.log_capture import log_line_starting_with, capture_logs_at

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emitter() -> tuple[RedisStreamBatchEmitter, list[dict]]:
    """Return (emitter, published_calls) where published_calls accumulates
    every dict passed to client.publish."""
    published: list[dict] = []

    client = MagicMock()

    async def capture_publish(
        stream: str,
        fields: dict,
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
        ttl_s: int | None = None,
    ) -> None:
        published.append(fields)

    client.publish = capture_publish

    emitter = RedisStreamBatchEmitter(
        client=client,
        result_stream_prefix="agent.results",
        correlation_id="test-corr",
        result_stream_ttl_s=3600,
    )
    return emitter, published


def _make_recording_client() -> tuple[MagicMock, list[dict]]:
    """Return (client, publish_calls) where publish_calls records the stream,
    maxlen and ttl_s of every client.publish call."""
    publish_calls: list[dict] = []
    client = MagicMock()

    async def record_publish(
        stream: str,
        fields: dict,
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
        ttl_s: int | None = None,
    ) -> None:
        publish_calls.append(
            {"stream": stream, "fields": fields, "maxlen": maxlen, "ttl_s": ttl_s}
        )

    client.publish = record_publish
    return client, publish_calls


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
# warnings reach the terminal payload, de-duplicated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", ["final", "error"])
@pytest.mark.parametrize(
    ("warnings", "expected"),
    [
        ([], []),
        (["approaching limit"], ["approaching limit"]),
        (["dup", "dup", "dup"], ["dup"]),
        (["warning A", "warning B"], ["warning A", "warning B"]),
    ],
    ids=["none", "one", "duplicates", "distinct"],
)
async def test_terminal_payload_carries_each_warning_once(terminal, warnings, expected):
    emitter, published = _make_emitter()
    for warning in warnings:
        await emitter.on_warning(warning)

    if terminal == "final":
        await emitter.on_final(_make_loop_result())
    else:
        await emitter.on_error(RuntimeError("boom"))

    (payload,) = [_decode_payload(fields) for fields in published]
    assert payload["warnings"] == expected


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


# ---------------------------------------------------------------------------
# Per-run result stream + TTL
# ---------------------------------------------------------------------------


async def test_on_final_publishes_to_per_run_stream_with_ttl():
    client, publish_calls = _make_recording_client()
    emitter = RedisStreamBatchEmitter(
        client=client,
        result_stream_prefix="agent.results",
        correlation_id="run-a",
        result_stream_ttl_s=3600,
    )

    await emitter.on_final(_make_loop_result())

    assert len(publish_calls) == 1
    assert publish_calls[0]["stream"] == "agent.results:run-a"
    assert publish_calls[0]["ttl_s"] == 3600
    assert publish_calls[0]["maxlen"] is None


async def test_on_error_publishes_to_per_run_stream_with_ttl():
    client, publish_calls = _make_recording_client()
    emitter = RedisStreamBatchEmitter(
        client=client,
        result_stream_prefix="agent.results",
        correlation_id="run-a",
        result_stream_ttl_s=3600,
    )

    await emitter.on_error(RuntimeError("boom"))

    assert len(publish_calls) == 1
    assert publish_calls[0]["stream"] == "agent.results:run-a"
    assert publish_calls[0]["ttl_s"] == 3600


# ---------------------------------------------------------------------------
# Logging masks sensitive fields while published payload remains original
# ---------------------------------------------------------------------------


async def test_on_final_masks_sensitive_fields_in_logs_but_not_published_payload():
    """Logs must not carry final_text/structured_output; the published envelope must."""
    emitter, published = _make_emitter()

    secret_text = "USER_SECRET_DATA"
    secret_output = {"key": "SECRET_VALUE"}
    task_secret_text = "TASK_SECRET"
    task_secret_output = {"data": "TASK_DATA"}
    task_name = "TASK_NAME_MARKER"

    result = LoopResult(
        final_text=secret_text,
        structured_output=secret_output,
        tool_invocations=0,
        iterations=1,
        stop_reason="completed",
        token_usage=TokenUsage(),
        tasks=[
            TaskRunSummary(
                name=task_name,
                order=0,
                final_text=task_secret_text,
                structured_output=task_secret_output,
                token_usage=TokenUsage(),
                iterations=1,
                tool_invocations=0,
                stop_reason="completed",
            ),
        ],
    )

    with capture_logs_at("DEBUG") as logs:
        await emitter.on_final(result)

    result_line = log_line_starting_with(logs, "agent.result ")
    assert "<redacted" in result_line

    log_output = "\n".join(logs)
    assert secret_text not in log_output
    assert secret_output["key"] not in log_output
    assert task_secret_text not in log_output
    assert task_secret_output["data"] not in log_output
    assert task_name in log_output

    assert len(published) == 1
    payload = _decode_payload(published[0])

    assert payload["final_text"] == secret_text
    assert payload["structured_output"] == secret_output
    assert len(payload["tasks"]) == 1
    task_payload = payload["tasks"][0]
    assert task_payload["name"] == task_name
    assert task_payload["final_text"] == task_secret_text
    assert task_payload["structured_output"] == task_secret_output


async def test_on_final_masks_error_text_in_logs_but_not_published_payload():
    """result.error can echo prompt content through str(exception); logs must not carry it."""
    emitter, published = _make_emitter()
    error_marker = "ERROR_ECHOING_USER_PROMPT_314"
    result = LoopResult(
        final_text=None,
        error=error_marker,
        tool_invocations=0,
        iterations=1,
        stop_reason="llm_error",
        token_usage=TokenUsage(),
    )

    with capture_logs_at("DEBUG") as logs:
        await emitter.on_final(result)

    result_line = log_line_starting_with(logs, "agent.result ")
    assert error_marker not in result_line
    assert "<redacted" in result_line
    assert "llm_error" in result_line, "stop_reason must stay readable"

    assert _decode_payload(published[0])["error"] == error_marker
