"""
Tests for consume_requests: requests run concurrently, the consumer reads only
as many messages as it has free run slots, and shutdown drains in-flight runs.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from loguru import logger
from main import consume_requests

from shared.redis_streams import StreamEnvelope, StreamMessage


def _message(message_id: str) -> StreamMessage:
    envelope = StreamEnvelope(type="agent.run", correlation_id=f"run-{message_id}", payload={})
    return StreamMessage(
        stream="agent.requests", message_id=message_id, fields=envelope.to_fields()
    )


class _FakeStreamClient:
    def __init__(self, batches: list[list[StreamMessage]]) -> None:
        self._batches = batches
        self.read_counts: list[int] = []

    async def read(self, streams, group, consumer, count, block_ms) -> list[StreamMessage]:
        self.read_counts.append(count)
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(0.01)
        return []


class _BlockingHandler:
    """Blocks each run until its own release event is set; raises for ``failing`` runs."""

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.started: list[str] = []
        self.release: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self._failing = failing

    async def handle(self, envelope: StreamEnvelope, message_id: str, stream: str) -> None:
        self.started.append(envelope.correlation_id)
        if envelope.correlation_id in self._failing:
            raise RuntimeError(f"handler failed for {envelope.correlation_id}")
        await self.release[envelope.correlation_id].wait()


async def _until(condition) -> None:
    async with asyncio.timeout(1):
        while not condition():
            await asyncio.sleep(0)


async def test_runs_overlap_free_slots_are_reused_and_stop_drains_in_flight_runs():
    client = _FakeStreamClient([[_message("1-0")], [_message("2-0")]])
    handler = _BlockingHandler()
    stop = asyncio.Event()
    consumer = asyncio.create_task(
        consume_requests(client, handler, "consumer-a", max_concurrent_runs=2, stop=stop)
    )

    # Both runs started while neither was released, and with both slots busy
    # the consumer stopped reading instead of claiming more messages.
    await _until(lambda: len(handler.started) == 2)
    assert handler.started == ["run-1-0", "run-2-0"]
    assert client.read_counts == [2, 1]

    # A finished run frees its slot for the next read.
    handler.release["run-1-0"].set()
    await _until(lambda: len(client.read_counts) > 2)
    assert client.read_counts[2] == 1

    # Stop waits for the run still in flight.
    stop.set()
    await asyncio.sleep(0.05)
    assert not consumer.done()

    handler.release["run-2-0"].set()
    await asyncio.wait_for(consumer, timeout=1)


async def test_failing_run_is_logged_and_frees_its_slot():
    client = _FakeStreamClient([[_message("1-0")], [_message("2-0")]])
    handler = _BlockingHandler(failing=frozenset({"run-1-0"}))
    stop = asyncio.Event()
    error_messages: list[str] = []
    sink_id = logger.add(error_messages.append, level="ERROR", format="{message}")

    try:
        consumer = asyncio.create_task(
            consume_requests(client, handler, "consumer-a", max_concurrent_runs=1, stop=stop)
        )
        await _until(lambda: len(handler.started) == 2)
    finally:
        logger.remove(sink_id)

    assert handler.started == ["run-1-0", "run-2-0"]
    assert any("1-0" in message for message in error_messages)

    stop.set()
    handler.release["run-2-0"].set()
    await asyncio.wait_for(consumer, timeout=1)
