"""
Tests for consume_requests: requests run concurrently, the consumer reads only
as many messages as it has free run slots, and shutdown drains in-flight runs.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

import pytest
import settings
from loguru import logger
from main import consume_requests
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from shared.redis_streams import StreamEnvelope, StreamMessage
from tests.log_capture import assert_masked_exception, capture_logs_at, log_line_starting_with


def _message(message_id: str) -> StreamMessage:
    envelope = StreamEnvelope(type="agent.run", correlation_id=f"run-{message_id}", payload={})
    return StreamMessage(
        stream="agent.requests", message_id=message_id, fields=envelope.to_fields()
    )


class _FakeStreamClient:
    def __init__(self, batches: list[list[StreamMessage]]) -> None:
        self._batches = batches
        self.read_counts: list[int] = []
        self.acked: list[str] = []

    async def read(self, streams, group, consumer, count, block_ms) -> list[StreamMessage]:
        self.read_counts.append(count)
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(0.01)
        return []

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append(message_id)


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
        consume_requests(client, handler, "consumer-a", max_concurrent_runs=2, stop=stop, read_retry_initial_delay_s=1, read_retry_max_delay_s=30)
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
            consume_requests(client, handler, "consumer-a", max_concurrent_runs=1, stop=stop, read_retry_initial_delay_s=1, read_retry_max_delay_s=30)
        )
        await _until(lambda: len(handler.started) == 2)
    finally:
        logger.remove(sink_id)

    assert handler.started == ["run-1-0", "run-2-0"]
    assert any("1-0" in message for message in error_messages)

    stop.set()
    handler.release["run-2-0"].set()
    await asyncio.wait_for(consumer, timeout=1)


class _RaisingHandler:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def handle(self, envelope: StreamEnvelope, message_id: str, stream: str) -> None:
        raise self._error


async def test_failing_run_logs_the_exception_class_without_its_message():
    secret_marker = "PROCESS_SECRET_86420"
    client = _FakeStreamClient([[_message("1-0")]])
    handler = _RaisingHandler(RuntimeError(f"blob fetch failed: {secret_marker}"))
    stop = asyncio.Event()

    with capture_logs_at("DEBUG") as messages:
        consumer = asyncio.create_task(
            consume_requests(client, handler, "consumer-a", max_concurrent_runs=1, stop=stop, read_retry_initial_delay_s=1, read_retry_max_delay_s=30)
        )
        await _until(lambda: any(m.startswith("failed to process") for m in messages))
        stop.set()
        await asyncio.wait_for(consumer, timeout=1)

    failure_line = log_line_starting_with(messages, "failed to process")
    assert "message_id=1-0" in failure_line
    assert "RuntimeError" in failure_line
    assert "<redacted" in failure_line
    assert secret_marker not in "".join(messages)


_POISON_PILL_PREFIX = "failed to parse message message_id="


async def _drive_poison_pill(
    bad_fields: dict[str, str],
) -> tuple[list[str], _FakeStreamClient, _BlockingHandler]:
    """Feed one unparseable message followed by a good one, and return what was logged.

    The good message only starts once the poison pill has been dealt with, so the
    consumer surviving the drop is what ends the wait.
    """
    poison_pill = StreamMessage(stream="agent.requests", message_id="1-0", fields=bad_fields)
    client = _FakeStreamClient([[poison_pill], [_message("2-0")]])
    handler = _BlockingHandler()
    stop = asyncio.Event()

    with capture_logs_at("DEBUG") as messages:
        consumer = asyncio.create_task(
            consume_requests(
                client,
                handler,
                "consumer-a",
                max_concurrent_runs=1,
                stop=stop,
                read_retry_initial_delay_s=1,
                read_retry_max_delay_s=30,
            )
        )
        await _until(lambda: handler.started == ["run-2-0"])
        stop.set()
        handler.release["run-2-0"].set()
        await asyncio.wait_for(consumer, timeout=1)

    return messages, client, handler


async def test_unparseable_payload_is_dropped_logging_validation_types_and_locations_only():
    secret_marker = "POISON_PAYLOAD_SECRET_13579"
    fields = {
        "type": "agent.run",
        "correlation_id": "run-1-0",
        # Valid JSON, but StreamEnvelope.payload is a dict — pydantic rejects a list.
        "payload": json.dumps([secret_marker]),
    }

    messages, client, handler = await _drive_poison_pill(fields)

    failure_line = log_line_starting_with(messages, _POISON_PILL_PREFIX)
    assert failure_line.startswith(f"{_POISON_PILL_PREFIX}1-0 ")
    assert failure_line.endswith("— dropping (poison pill)")
    assert "validation=ValidationError" in failure_line
    assert "1 error(s)" in failure_line
    assert "dict_type at payload" in failure_line
    assert secret_marker not in "".join(messages)
    assert client.acked == ["1-0"]
    assert handler.started == ["run-2-0"]


async def test_undecodable_payload_is_dropped_logging_the_class_name_and_a_digest_only():
    secret_marker = "POISON_JSON_SECRET_24680"
    fields = {
        "type": "agent.run",
        "correlation_id": "run-1-0",
        "payload": f'{{"api_key": "{secret_marker}", BROKEN',
    }

    messages, client, handler = await _drive_poison_pill(fields)

    failure_line = log_line_starting_with(messages, _POISON_PILL_PREFIX)
    assert failure_line.startswith(f"{_POISON_PILL_PREFIX}1-0 ")
    assert failure_line.endswith("— dropping (poison pill)")
    assert_masked_exception(failure_line, "JSONDecodeError")
    assert secret_marker not in "".join(messages)
    assert client.acked == ["1-0"]
    assert handler.started == ["run-2-0"]


class _ScriptedStreamClient:
    """Plays ``script`` one read at a time: an exception is raised, a list is returned."""

    def __init__(self, script: list[Exception | list[StreamMessage]]) -> None:
        self._script = script
        self.ensured_groups: list[tuple[str, str]] = []

    async def read(self, streams, group, consumer, count, block_ms) -> list[StreamMessage]:
        if not self._script:
            await asyncio.sleep(0.01)
            return []
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def ensure_group(self, stream, group, start_id="$", mkstream=True) -> None:
        self.ensured_groups.append((stream, group))


async def test_missing_consumer_group_is_recreated_and_the_next_request_runs():
    client = _ScriptedStreamClient(
        [ResponseError("NOGROUP No such key 'agent.requests' or consumer group"), [_message("1-0")]]
    )
    handler = _BlockingHandler()
    stop = asyncio.Event()
    consumer = asyncio.create_task(
        consume_requests(client, handler, "consumer-a", max_concurrent_runs=1, stop=stop, read_retry_initial_delay_s=1, read_retry_max_delay_s=30)
    )

    await _until(lambda: handler.started == ["run-1-0"])
    assert client.ensured_groups == [
        (settings.AGENT_REQUEST_STREAM, settings.AGENT_CONSUMER_GROUP)
    ]

    stop.set()
    handler.release["run-1-0"].set()
    await asyncio.wait_for(consumer, timeout=1)


async def test_read_errors_back_off_doubling_to_a_cap_and_reset_after_a_successful_read():
    down = RedisConnectionError("redis down")
    client = _ScriptedStreamClient([down] * 7 + [[_message("1-0")], down, [_message("2-0")]])
    handler = _BlockingHandler()
    stop = asyncio.Event()
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    consumer = asyncio.create_task(
        consume_requests(
            client, handler, "consumer-a", max_concurrent_runs=2, stop=stop, sleep=record_sleep, read_retry_initial_delay_s=1, read_retry_max_delay_s=30
        )
    )

    await _until(lambda: handler.started == ["run-1-0", "run-2-0"])
    assert delays == [1, 2, 4, 8, 16, 30, 30, 1]

    stop.set()
    handler.release["run-1-0"].set()
    handler.release["run-2-0"].set()
    await asyncio.wait_for(consumer, timeout=1)


class _BlockedStreamClient:
    async def read(self, streams, group, consumer, count, block_ms) -> list[StreamMessage]:
        await asyncio.Event().wait()


async def test_cancelling_the_consumer_during_a_blocked_read_ends_it():
    consumer = asyncio.create_task(
        consume_requests(
            _BlockedStreamClient(),
            _BlockingHandler(),
            "consumer-a",
            max_concurrent_runs=1,
            stop=asyncio.Event(),
            read_retry_initial_delay_s=1, read_retry_max_delay_s=30,
        )
    )
    await asyncio.sleep(0.05)

    consumer.cancel()
    await asyncio.wait({consumer}, timeout=1)

    assert consumer.cancelled()


async def test_a_permanent_redis_error_ends_the_consumer():
    client = _ScriptedStreamClient([ResponseError("WRONGTYPE Operation against a key")])

    async def no_sleep(delay: float) -> None:
        pass

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        await asyncio.wait_for(
            consume_requests(
                client,
                _BlockingHandler(),
                "consumer-a",
                max_concurrent_runs=1,
                stop=asyncio.Event(),
                sleep=no_sleep,
                read_retry_initial_delay_s=1, read_retry_max_delay_s=30,
            ),
            timeout=1,
        )
