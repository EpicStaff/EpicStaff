import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from src.shared.audit.client import AuditClient
from src.shared.models import SessionAuditEvent


def make_event(id_: str) -> SessionAuditEvent:
    return SessionAuditEvent(
        id=id_,
        org_id=1,
        session_id=1,
        kind="node",
        status="completed",
        event_time=datetime.now(timezone.utc),
    )


class RecordingTransportHandler:
    """Fake transport recording every request payload; always succeeds."""

    def __init__(self):
        self.calls: list[list[dict]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content))
        return httpx.Response(200, json={"received": len(self.calls[-1])})


class FlakyTransportHandler:
    """Fails `fail_count` times, then succeeds. Tracks attempts."""

    def __init__(self, fail_count: int):
        self.fail_count = fail_count
        self.attempts = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise httpx.ConnectError("simulated failure")
        return httpx.Response(200, json={"received": 1})


class PartialFailureTransportHandler:
    """Simulates the ingest route's 207 response: fails a specific set of
    event ids `fail_ids_first_n_attempts` times each, then reports them as
    succeeded. Tracks every payload it actually received."""

    def __init__(self, always_failing_ids: set[str], fail_count: int):
        self.always_failing_ids = always_failing_ids
        self.fail_count = fail_count
        self.attempts = 0
        self.payloads: list[list[dict]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        payload = json.loads(request.content)
        self.payloads.append(payload)

        if self.attempts <= self.fail_count:
            failed_ids = [e["id"] for e in payload if e["id"] in self.always_failing_ids]
        else:
            failed_ids = []

        if failed_ids:
            return httpx.Response(
                207,
                json={"received": len(payload) - len(failed_ids), "failed_ids": failed_ids},
            )
        return httpx.Response(200, json={"received": len(payload)})


class AlwaysFailingTransportHandler:
    def __init__(self):
        self.attempts = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        raise httpx.ConnectError("simulated persistent failure")


class StatusCodeTransportHandler:
    """Always answers with a fixed HTTP status. Tracks attempts."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        self.attempts = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        return httpx.Response(self.status_code, json={"detail": "simulated"})


def build_client(handler, **overrides) -> AuditClient:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs = dict(
        base_url="http://auditor.test",
        ingest_path="/api/audit/sessions/events",
        api_key="test-key",
        http_client=http_client,
        max_retries=3,
    )
    kwargs.update(overrides)
    return AuditClient(**kwargs)


@pytest.mark.asyncio
async def test_batches_on_size():
    """A batch flushes as soon as batch_size is reached, without waiting for the interval."""
    transport = RecordingTransportHandler()
    client = build_client(transport, batch_size=3, batch_interval_seconds=10)

    for i in range(3):
        await client.emit(make_event(f"e{i}"))

    await asyncio.sleep(0.2)

    assert len(transport.calls) == 1
    assert len(transport.calls[0]) == 3

    await client.shutdown()


@pytest.mark.asyncio
async def test_batches_on_time():
    """A partial batch flushes once the interval elapses, without waiting for batch_size."""
    transport = RecordingTransportHandler()
    client = build_client(transport, batch_size=100, batch_interval_seconds=0.2)

    await client.emit(make_event("only-one"))
    await asyncio.sleep(0.4)

    assert len(transport.calls) == 1
    assert len(transport.calls[0]) == 1

    await client.shutdown()


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    """A batch that fails twice then succeeds is delivered, not dropped."""
    transport = FlakyTransportHandler(fail_count=2)
    client = build_client(
        transport, batch_size=1, batch_interval_seconds=10, max_retries=3
    )

    await client.emit(make_event("retry-me"))
    # real backoff delays total ~0.7s (0.2 + 0.5) across 2 retries before success
    await asyncio.sleep(2)

    assert transport.attempts == 3  # 2 failures + 1 success
    await client.shutdown()


@pytest.mark.asyncio
async def test_207_partial_failure_retries_only_the_failed_ids():
    """A 207 response (partial bulk-write failure) is not treated as
    success - the client retries just the events the server reported as
    failed_ids, not the whole batch and not nothing."""
    transport = PartialFailureTransportHandler(
        always_failing_ids={"bad-1"}, fail_count=1
    )
    client = build_client(transport, batch_size=2, batch_interval_seconds=10)

    await client.emit(make_event("ok-1"))
    await client.emit(make_event("bad-1"))
    await asyncio.sleep(2)

    assert transport.attempts == 2
    assert [e["id"] for e in transport.payloads[0]] == ["ok-1", "bad-1"]
    # the retry only resends the event that actually failed
    assert [e["id"] for e in transport.payloads[1]] == ["bad-1"]

    await client.shutdown()


@pytest.mark.asyncio
async def test_207_persistent_partial_failure_drops_remaining_ids_without_raising():
    """A batch whose failed_ids never clear across max_retries is dropped
    (logged), not retried forever and not silently marked delivered."""
    transport = PartialFailureTransportHandler(
        always_failing_ids={"doomed"}, fail_count=99
    )
    client = build_client(
        transport, batch_size=1, batch_interval_seconds=10, max_retries=3
    )

    await client.emit(make_event("doomed"))
    await asyncio.sleep(2)

    assert transport.attempts == 3  # exhausted max_retries, gave up
    await client.shutdown()


@pytest.mark.asyncio
async def test_persistent_failure_drops_batch_without_raising():
    """A batch that always fails is dropped after max_retries, never raises, never retries forever."""
    transport = AlwaysFailingTransportHandler()
    client = build_client(
        transport, batch_size=1, batch_interval_seconds=10, max_retries=3
    )

    await client.emit(make_event("doomed"))
    # real backoff delays total ~0.7s (0.2 + 0.5) across the 2 retries before giving up
    await asyncio.sleep(2)

    assert (
        transport.attempts == 3
    )  # exhausted max_retries, gave up - didn't retry forever
    await client.shutdown()


@pytest.mark.asyncio
async def test_4xx_response_is_dropped_without_retry():
    """A 4xx (e.g. 422 validation) can never succeed on resend - one attempt only."""
    transport = StatusCodeTransportHandler(422)
    client = build_client(
        transport, batch_size=1, batch_interval_seconds=10, max_retries=3
    )

    await client.emit(make_event("rejected"))
    await asyncio.sleep(1)

    assert transport.attempts == 1
    await client.shutdown()


@pytest.mark.asyncio
async def test_5xx_response_is_retried_up_to_max_retries():
    transport = StatusCodeTransportHandler(503)
    client = build_client(
        transport, batch_size=1, batch_interval_seconds=10, max_retries=3
    )

    await client.emit(make_event("server-down"))
    # real backoff delays total ~0.7s (0.2 + 0.5) across the 2 retries
    await asyncio.sleep(2)

    assert transport.attempts == 3
    await client.shutdown()


@pytest.mark.asyncio
async def test_emit_on_full_queue_drops_event_without_raising_or_blocking():
    """During an auditor outage the queue fills up; emit() must drop, not grow or block."""
    transport = RecordingTransportHandler()
    client = build_client(
        transport, batch_size=100, batch_interval_seconds=10, max_queue_size=2
    )
    # Stop the flush loop so nothing drains the queue, like a stalled loop in an outage.
    client._flush_task.cancel()
    await asyncio.sleep(0)

    for index in range(5):
        await asyncio.wait_for(client.emit(make_event(f"e{index}")), timeout=0.5)

    assert client._queue.qsize() == 2
    assert client._dropped_on_full_queue_count == 3

    await client.shutdown()
    # shutdown still flushes the events that did fit in the queue
    assert [event["id"] for event in transport.calls[0]] == ["e0", "e1"]


@pytest.mark.asyncio
async def test_disabled_client_never_sends_and_starts_no_background_task():
    client = AuditClient(
        base_url="http://auditor.test",
        ingest_path="/api/audit/sessions/events",
        api_key="test-key",
        enabled=False,
    )

    assert client._flush_task is None

    await client.emit(
        make_event("should-not-send")
    )  # must not raise even though disabled
    await client.shutdown()  # must not raise


def test_immediate_mode_construction_requires_no_running_event_loop():
    """
    Regression test: __init__ used to unconditionally call asyncio.create_task,
    which raises RuntimeError with no running loop - exactly django_app's
    situation (register_message runs via asgiref.sync.async_to_sync, a
    per-call temporary loop; get_session_audit_writer() itself is called as
    plain sync code before that wrapper ever starts). Deliberately NOT an
    async test - this must work with zero event loop in play at all.
    """
    client = AuditClient(
        base_url="http://auditor.test",
        ingest_path="/api/audit/sessions/events",
        api_key="test-key",
        enabled=True,
        immediate=True,
    )
    assert client._flush_task is None


@pytest.mark.asyncio
async def test_immediate_mode_sends_synchronously_without_a_background_task():
    transport = RecordingTransportHandler()
    client = build_client(transport, immediate=True)

    assert client._flush_task is None

    await client.emit(make_event("sent-immediately"))

    # no need to sleep/wait for a background loop - immediate mode sends
    # inline within emit() itself
    assert len(transport.calls) == 1
    assert transport.calls[0][0]["id"] == "sent-immediately"

    await client.shutdown()
