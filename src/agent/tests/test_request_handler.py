"""
Tests for RequestHandler's pre-runner failure path: the fallback emitter
publishes ``agent.error`` to the run's own result stream, derived from the
envelope's correlation_id.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from app.request_handler import RequestHandler
from shared.redis_streams import StreamEnvelope


def _make_recording_client() -> tuple[MagicMock, list[dict]]:
    publish_calls: list[dict] = []
    client = MagicMock()

    async def record_publish(
        stream: str,
        fields: dict,
        maxlen: int | None = 1_000_000,
        approximate: bool = True,
        ttl_s: int | None = None,
    ) -> None:
        publish_calls.append({"stream": stream, "fields": fields, "ttl_s": ttl_s})

    client.publish = record_publish
    client.ack = AsyncMock(return_value=1)
    return client, publish_calls


def _make_handler(client: MagicMock, loader: MagicMock) -> RequestHandler:
    return RequestHandler(
        loader=loader,
        factory=MagicMock(),
        redis_client=client,
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
        request_stream="agent.requests",
        consumer_group="agent-executors",
    )


async def test_load_failure_publishes_agent_error_to_per_run_stream_and_acks():
    client, publish_calls = _make_recording_client()
    loader = MagicMock()
    loader.load = AsyncMock(side_effect=RuntimeError("request blob missing"))
    handler = _make_handler(client, loader)
    envelope = StreamEnvelope(
        type="agent.run",
        correlation_id="run-a",
        payload={"request_key": "agent:request:run-a"},
    )

    await handler.handle(envelope, message_id="1-0", stream="agent.requests")

    assert len(publish_calls) == 1
    assert publish_calls[0]["stream"] == "agent.results:run-a"
    assert publish_calls[0]["ttl_s"] == 3600
    assert publish_calls[0]["fields"]["type"] == "agent.error"
    assert json.loads(publish_calls[0]["fields"]["payload"])["error"] == "request blob missing"
    client.ack.assert_awaited_once_with("agent.requests", "agent-executors", "1-0")

