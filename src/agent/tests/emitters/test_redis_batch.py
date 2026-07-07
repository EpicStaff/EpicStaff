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
from shared.models.agent_service import LoopResult, TokenUsage
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
