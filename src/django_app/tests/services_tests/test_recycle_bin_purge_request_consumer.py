import fakeredis
import pytest
import redis

from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_CONSUMER_GROUP,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
)
from tables.services.recycle_bin import purge_request_consumer as consumer_module
from tables.services.recycle_bin.purge_request_consumer import RecycleBinPurgeRequestConsumer
from tables.services.recycle_bin.purge_service import PurgeService
from utils.logger import logger

# The consumer closes stale database connections around each purge.
pytestmark = pytest.mark.django_db


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def purge_calls(monkeypatch):
    """Replaces the purge itself (tested in test_recycle_bin_purge.py) and records each run."""
    calls = []

    def fake_purge_expired(*args, **kwargs):
        calls.append(1)
        return {"tables.Graph": 2, "tables.Agent": 1}

    monkeypatch.setattr(PurgeService, "purge_expired", fake_purge_expired)
    return calls


@pytest.fixture
def logged():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    yield records
    logger.remove(sink_id)


def _request_purge(redis_client, requested_at="2026-01-01T03:00:00+00:00"):
    redis_client.xadd(RECYCLE_BIN_PURGE_STREAM, {RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD: requested_at})


def _pending_count(redis_client) -> int:
    return redis_client.xpending(RECYCLE_BIN_PURGE_STREAM, RECYCLE_BIN_PURGE_CONSUMER_GROUP)[
        "pending"
    ]


def _consumer(redis_client, name="host-a") -> RecycleBinPurgeRequestConsumer:
    consumer = RecycleBinPurgeRequestConsumer(redis_client, name, sleep=lambda _seconds: None)
    consumer.start()
    return consumer


def test_one_request_runs_one_purge_and_is_acknowledged(redis_client, purge_calls):
    consumer = _consumer(redis_client)
    _request_purge(redis_client)

    handled = consumer.process_new(block_milliseconds=None)

    assert handled == 1
    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0


def test_no_request_runs_no_purge(redis_client, purge_calls):
    consumer = _consumer(redis_client)

    assert consumer.process_new(block_milliseconds=None) == 0
    assert purge_calls == []


def test_a_backlog_of_requests_runs_one_purge_and_acknowledges_all(redis_client, purge_calls):
    consumer = _consumer(redis_client)
    for day in range(1, 4):
        _request_purge(redis_client, requested_at=f"2026-01-0{day}T03:00:00+00:00")

    handled = consumer.process_new(block_milliseconds=None)

    assert handled == 3
    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0


def test_requests_added_before_the_group_existed_are_served(redis_client, purge_calls):
    _request_purge(redis_client)
    consumer = _consumer(redis_client)

    assert consumer.process_new(block_milliseconds=None) == 1
    assert len(purge_calls) == 1


def test_a_failing_purge_is_logged_and_its_requests_are_still_acknowledged(
    redis_client, monkeypatch, logged
):
    def failing_purge_expired(*args, **kwargs):
        raise RuntimeError("storage is down")

    monkeypatch.setattr(PurgeService, "purge_expired", failing_purge_expired)
    consumer = _consumer(redis_client)
    _request_purge(redis_client)

    consumer.process_new(block_milliseconds=None)

    assert _pending_count(redis_client) == 0
    assert any(
        record["level"].name == "ERROR" and "purge failed" in record["message"] for record in logged
    )
    # The failed request is not served again.
    assert consumer.process_new(block_milliseconds=None) == 0


def test_two_consumers_in_one_group_run_one_purge_for_one_request(redis_client, purge_calls):
    first = _consumer(redis_client, name="host-a")
    second = _consumer(redis_client, name="host-b")
    _request_purge(redis_client)

    handled = first.process_new(block_milliseconds=None) + second.process_new(
        block_milliseconds=None
    )

    assert handled == 1
    assert len(purge_calls) == 1


def test_start_serves_requests_this_consumer_read_but_never_acknowledged(
    redis_client, purge_calls
):
    crashed = _consumer(redis_client, name="host-a")
    _request_purge(redis_client)
    redis_client.xreadgroup(
        RECYCLE_BIN_PURGE_CONSUMER_GROUP, "host-a", {RECYCLE_BIN_PURGE_STREAM: ">"}
    )
    assert _pending_count(redis_client) == 1
    assert purge_calls == []

    restarted = RecycleBinPurgeRequestConsumer(redis_client, "host-a")
    restarted.start()

    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0
    assert crashed.process_new(block_milliseconds=None) == 0


def test_purge_logs_start_with_requested_at_and_finish_with_counts(
    redis_client, purge_calls, logged
):
    consumer = _consumer(redis_client)
    _request_purge(redis_client, requested_at="2026-02-03T03:00:00+00:00")

    consumer.process_new(block_milliseconds=None)

    messages = [record["message"] for record in logged]
    assert any("started" in message and "2026-02-03T03:00:00+00:00" in message for message in messages)
    assert any("3 row(s) purged" in message and "tables.Graph" in message for message in messages)


def test_an_empty_purge_is_reported_as_nothing_to_purge(redis_client, monkeypatch, logged):
    monkeypatch.setattr(PurgeService, "purge_expired", lambda *args, **kwargs: {})
    consumer = _consumer(redis_client)
    _request_purge(redis_client)

    consumer.process_new(block_milliseconds=None)

    assert any("nothing to purge" in record["message"] for record in logged)


def test_run_starts_over_after_a_redis_error(redis_client, purge_calls, monkeypatch):
    consumer = RecycleBinPurgeRequestConsumer(redis_client, "host-a", sleep=lambda _seconds: None)
    _request_purge(redis_client)
    real_process_new = consumer.process_new
    attempts = []

    def process_new_failing_once(block_milliseconds):
        attempts.append(1)
        if len(attempts) == 1:
            raise redis.ConnectionError("connection reset")
        real_process_new(block_milliseconds=None)
        raise KeyboardInterrupt  # ends run(), which loops forever

    monkeypatch.setattr(consumer, "process_new", process_new_failing_once)

    with pytest.raises(KeyboardInterrupt):
        consumer.run()

    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0


def test_a_request_is_acknowledged_even_when_closing_connections_after_the_purge_fails(
    redis_client, purge_calls, monkeypatch
):
    consumer = _consumer(redis_client)
    _request_purge(redis_client)

    def failing_close():
        raise RuntimeError("connection is gone")

    monkeypatch.setattr(consumer_module, "close_old_connections", failing_close)

    consumer.process_new(block_milliseconds=None)

    assert _pending_count(redis_client) == 0


def test_run_recreates_the_group_and_serves_new_requests_after_the_stream_is_deleted(
    redis_client, purge_calls, monkeypatch
):
    consumer = RecycleBinPurgeRequestConsumer(redis_client, "host-a", sleep=lambda _seconds: None)
    consumer.start()
    redis_client.delete(RECYCLE_BIN_PURGE_STREAM)
    real_process_new = consumer.process_new
    attempts = []

    def process_new_then_stop(block_milliseconds):
        attempts.append(1)
        if len(attempts) == 1:
            # Fails with NOGROUP: neither stream nor group exist any more.
            return real_process_new(block_milliseconds=None)
        _request_purge(redis_client)
        real_process_new(block_milliseconds=None)
        raise KeyboardInterrupt  # ends run(), which loops forever

    monkeypatch.setattr(consumer, "process_new", process_new_then_stop)

    with pytest.raises(KeyboardInterrupt):
        consumer.run()

    assert len(purge_calls) == 1
    assert _pending_count(redis_client) == 0
