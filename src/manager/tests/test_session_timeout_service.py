import asyncio
import json

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from services.redis_service import RedisService
from services.session_timeout_service import SessionTimeoutService

TIMEOUT_CHANNEL = "test:session_timeout"


class FakeSessionRepository:
    """Stands in for the database: returns queued results, raising any exception queued."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def get_overdue_session_ids(self):
        self.calls += 1
        result = self.results.pop(0) if self.results else []
        if isinstance(result, Exception):
            raise result
        return result


@pytest_asyncio.fixture
async def redis_service():
    service = RedisService(host="unused", port=0)
    service.aioredis_client = FakeAsyncRedis()
    yield service
    await service.aioredis_client.aclose()


@pytest_asyncio.fixture
async def timeout_subscription(redis_service):
    pubsub = redis_service.aioredis_client.pubsub()
    await pubsub.subscribe(TIMEOUT_CHANNEL)
    # Consume the subscribe confirmation so only published messages remain.
    await pubsub.get_message(timeout=1)
    yield pubsub
    await pubsub.aclose()


async def _published_messages(pubsub, expected_count: int, timeout: float = 2.0) -> list[dict]:
    messages = []
    deadline = asyncio.get_running_loop().time() + timeout
    while len(messages) < expected_count and asyncio.get_running_loop().time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if message is not None:
            messages.append(json.loads(message["data"]))
    return messages


def _build_service(redis_service, repository, sweep_interval_seconds=60.0):
    return SessionTimeoutService(
        redis_service=redis_service,
        session_timeout_channel=TIMEOUT_CHANNEL,
        session_repository=repository,
        sweep_interval_seconds=sweep_interval_seconds,
    )


@pytest.mark.asyncio
async def test_sweep_once_publishes_timeout_for_each_overdue_session(
    redis_service, timeout_subscription
):
    service = _build_service(redis_service, FakeSessionRepository([[11, 12, 13]]))

    await service.sweep_once()

    messages = await _published_messages(timeout_subscription, expected_count=3)
    assert messages == [
        {"session_id": 11, "action": "timeout"},
        {"session_id": 12, "action": "timeout"},
        {"session_id": 13, "action": "timeout"},
    ]


@pytest.mark.asyncio
async def test_sweep_once_with_no_overdue_sessions_publishes_nothing(
    redis_service, timeout_subscription
):
    service = _build_service(redis_service, FakeSessionRepository([[]]))

    await service.sweep_once()

    assert await _published_messages(timeout_subscription, expected_count=1, timeout=0.2) == []


@pytest.mark.asyncio
async def test_sweep_loop_survives_repository_error_and_keeps_sweeping(
    redis_service, timeout_subscription
):
    repository = FakeSessionRepository([ConnectionError("database is down"), [42]])
    service = _build_service(redis_service, repository, sweep_interval_seconds=0.01)

    await service.start()
    try:
        messages = await _published_messages(timeout_subscription, expected_count=1)
    finally:
        await service.stop()

    assert messages == [{"session_id": 42, "action": "timeout"}]
    assert repository.calls >= 2


@pytest.mark.asyncio
async def test_start_returns_immediately_and_stop_cancels_the_loop(redis_service):
    repository = FakeSessionRepository([])
    service = _build_service(redis_service, repository, sweep_interval_seconds=3600)

    await asyncio.wait_for(service.start(), timeout=1)
    sweep_task = service._task
    await asyncio.sleep(0)

    await service.stop()

    assert sweep_task.cancelled()
    assert service._task is None
    assert repository.calls == 1
