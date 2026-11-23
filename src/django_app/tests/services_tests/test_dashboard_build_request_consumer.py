import fakeredis
import pytest

from src.shared.redis_streams import (
    DASHBOARD_BUILD_CONSUMER_GROUP,
    DASHBOARD_BUILD_REQUESTED_AT_FIELD,
    DASHBOARD_BUILD_STREAM,
)
from tables.services.dashboard import build_request_consumer as consumer_module
from tables.services.dashboard.build_request_consumer import DashboardBuildRequestConsumer

pytestmark = pytest.mark.django_db


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def build_calls(monkeypatch):
    calls = []

    def fake_build_due_reports(now):
        calls.append(now)
        return [], []

    monkeypatch.setattr(consumer_module, "build_due_reports", fake_build_due_reports)
    return calls


def _request_build(redis_client):
    redis_client.xadd(
        DASHBOARD_BUILD_STREAM, {DASHBOARD_BUILD_REQUESTED_AT_FIELD: "2026-11-23T06:00:00+00:00"}
    )


def _pending_count(redis_client) -> int:
    return redis_client.xpending(DASHBOARD_BUILD_STREAM, DASHBOARD_BUILD_CONSUMER_GROUP)["pending"]


def _consumer(redis_client) -> DashboardBuildRequestConsumer:
    consumer = DashboardBuildRequestConsumer(redis_client, "host-a", sleep=lambda _seconds: None)
    consumer.start()
    return consumer


def test_one_request_runs_one_check_and_is_acknowledged(redis_client, build_calls):
    consumer = _consumer(redis_client)
    _request_build(redis_client)

    assert consumer.process_new(block_milliseconds=None) == 1
    assert len(build_calls) == 1
    assert _pending_count(redis_client) == 0


def test_piled_up_requests_run_one_check(redis_client, build_calls):
    consumer = _consumer(redis_client)
    for _ in range(3):
        _request_build(redis_client)

    assert consumer.process_new(block_milliseconds=None) == 3
    assert len(build_calls) == 1
    assert _pending_count(redis_client) == 0


def test_failed_check_is_still_acknowledged(redis_client, monkeypatch):
    def fail(now):
        raise RuntimeError("boom")

    monkeypatch.setattr(consumer_module, "build_due_reports", fail)
    consumer = _consumer(redis_client)
    _request_build(redis_client)

    consumer.process_new(block_milliseconds=None)

    assert _pending_count(redis_client) == 0
