import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import settings
from fakeredis import FakeAsyncRedis
from helpers.logger import logger
from redis.exceptions import ConnectionError as RedisConnectionError

from services.redis_service import RedisService
from services.schedule_service import ScheduleService, ScheduleSyncError
from src.shared.models import ScheduleTriggerNodePayload


class FakeScheduleRepository:
    """Stands in for the database: one result per call, the last one repeating.

    None as a result means the DB could not be read, as the real repository reports it.
    """

    def __init__(self, *results, on_call=None):
        self.results = list(results)
        self.on_call = on_call
        self.calls = 0

    async def get_all_active_schedule_nodes(self):
        self.calls += 1
        if self.on_call is not None:
            await self.on_call()
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class FlakyPubSubRedis(FakeAsyncRedis):
    """Fake Redis whose first pub/sub subscriptions break, like a Redis restart would."""

    def __init__(self, *args, failing_subscriptions: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.failing_subscriptions = failing_subscriptions
        self.subscription_count = 0

    def pubsub(self, **kwargs):
        pubsub = super().pubsub(**kwargs)
        self.subscription_count += 1
        if self.subscription_count <= self.failing_subscriptions:

            async def broken_listen():
                raise RedisConnectionError("Connection closed by server.")
                yield  # pragma: no cover - makes this an async generator

            pubsub.listen = broken_listen
        return pubsub


class UnreachableAtFirstRedis(FakeAsyncRedis):
    """Fake Redis whose first subscribe call fails, as when Redis is still starting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe_attempts = 0

    def pubsub(self, **kwargs):
        pubsub = super().pubsub(**kwargs)
        real_subscribe = pubsub.subscribe

        async def subscribe(*channels):
            self.subscribe_attempts += 1
            if self.subscribe_attempts == 1:
                raise RedisConnectionError("Connection refused.")
            return await real_subscribe(*channels)

        pubsub.subscribe = subscribe
        return pubsub


def _repeat_node(node_id: int, every: int = 1) -> ScheduleTriggerNodePayload:
    return ScheduleTriggerNodePayload(
        id=node_id,
        node_name=f"schedule-{node_id}",
        graph=1,
        is_active=True,
        run_mode="repeat",
        start_date_time=datetime.now(UTC) - timedelta(hours=1),
        every=every,
        unit="hours",
        end_type="never",
    )


def _once_node(node_id: int, start: datetime) -> ScheduleTriggerNodePayload:
    return ScheduleTriggerNodePayload(
        id=node_id,
        node_name=f"once-{node_id}",
        graph=1,
        is_active=True,
        run_mode="once",
        start_date_time=start,
    )


def _node_update_message(action: str, node: ScheduleTriggerNodePayload) -> str:
    return json.dumps(
        {
            "action": "node_update",
            "data": {"action": action, "node": node.model_dump(mode="json")},
        }
    )


def _redis_service_with(client) -> RedisService:
    service = RedisService(host="unused", port=0)
    service.aioredis_client = client
    return service


@pytest_asyncio.fixture
async def redis_service():
    service = _redis_service_with(FakeAsyncRedis())
    yield service
    await service.aioredis_client.aclose()


@pytest_asyncio.fixture
async def schedule_channel_subscription(redis_service):
    pubsub = redis_service.aioredis_client.pubsub()
    await pubsub.subscribe(settings.SCHEDULE_CHANNEL)
    await pubsub.get_message(timeout=1)
    yield pubsub
    await pubsub.aclose()


@pytest_asyncio.fixture
async def schedule_service(redis_service):
    service = ScheduleService(redis_service=redis_service)
    # Paused: jobs are registered and inspectable but never fire during a test.
    service.scheduler.start(paused=True)
    yield service
    service.scheduler.shutdown(wait=False)


@pytest_asyncio.fixture
async def running_schedule_service(redis_service):
    service = ScheduleService(redis_service=redis_service)
    service.scheduler.start()
    yield service
    service.scheduler.shutdown(wait=False)


@pytest.fixture
def no_reconnect_delay(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULE_LISTENER_RECONNECT_DELAY_SECONDS", 0)
    monkeypatch.setattr(settings, "SYNC_RETRY_DELAY", 0)


@pytest.fixture
def captured_logs():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    yield records
    logger.remove(sink_id)


async def _stop_listener_and_scheduler(service: ScheduleService):
    service.listener_task.cancel()
    await asyncio.gather(service.listener_task, return_exceptions=True)
    service.scheduler.shutdown(wait=False)


async def _published_actions(pubsub, timeout: float = 0.3) -> list[dict]:
    messages = []
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if message is not None:
            messages.append(json.loads(message["data"]))
    return messages


async def _wait_until_subscribed(client, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while dict(await client.pubsub_numsub(settings.SCHEDULE_CHANNEL)).get(
        settings.SCHEDULE_CHANNEL.encode(), 0
    ) == 0:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("listener did not subscribe in time")
        await asyncio.sleep(0.01)


async def _wait_until(condition, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_reconcile_removes_vanished_node_and_adds_new_one_without_deactivate(
    schedule_service, schedule_channel_subscription
):
    await schedule_service.add_schedule(_repeat_node(1))
    await schedule_service.add_schedule(_repeat_node(2))
    schedule_service.repository = FakeScheduleRepository([_repeat_node(2), _repeat_node(3)])

    await schedule_service.reconcile_schedules_with_db()

    assert schedule_service.scheduler.get_job("schedule_1") is None
    assert schedule_service.scheduler.get_job("schedule_2") is not None
    assert schedule_service.scheduler.get_job("schedule_3") is not None
    assert set(schedule_service.schedule_nodes) == {2, 3}
    assert await _published_actions(schedule_channel_subscription) == []


@pytest.mark.asyncio
async def test_reconcile_replaces_job_whose_node_changed(schedule_service):
    await schedule_service.add_schedule(_repeat_node(1, every=1))
    schedule_service.repository = FakeScheduleRepository([_repeat_node(1, every=6)])

    await schedule_service.reconcile_schedules_with_db()

    scheduled_node = schedule_service.scheduler.get_job("schedule_1").args[0]
    assert scheduled_node.every == 6


@pytest.mark.asyncio
async def test_reconcile_does_not_re_add_once_node_that_already_fired(
    running_schedule_service, schedule_channel_subscription
):
    once_node = _once_node(7, start=datetime.now(UTC) - timedelta(seconds=1))
    await running_schedule_service.add_schedule(once_node)
    first_fire = await _published_actions(schedule_channel_subscription, timeout=1.5)
    assert {"action": "run_session", "node_id": 7} in first_fire
    # Django has not processed the 'deactivate' yet, so the node is still active.
    future_once_node = _once_node(8, start=datetime.now(UTC) + timedelta(hours=1))
    running_schedule_service.repository = FakeScheduleRepository([once_node, future_once_node])

    await running_schedule_service.reconcile_schedules_with_db()

    assert running_schedule_service.scheduler.get_job("schedule_7") is None
    assert running_schedule_service.scheduler.get_job("schedule_8") is not None
    assert await _published_actions(schedule_channel_subscription, timeout=1.5) == []


@pytest.mark.asyncio
async def test_reconcile_fires_never_seen_once_node_within_misfire_grace(
    running_schedule_service, schedule_channel_subscription
):
    # Its create message was lost during the outage; the start passed 5 s ago,
    # inside APScheduler's 30 s misfire grace, so the live path would have fired it.
    missed_once_node = _once_node(9, start=datetime.now(UTC) - timedelta(seconds=5))
    running_schedule_service.repository = FakeScheduleRepository([missed_once_node])

    await running_schedule_service.reconcile_schedules_with_db()

    published = await _published_actions(schedule_channel_subscription, timeout=1.5)
    assert {"action": "run_session", "node_id": 9} in published


@pytest.mark.asyncio
async def test_reconcile_retries_once_node_whose_registration_failed(
    running_schedule_service, schedule_channel_subscription, monkeypatch
):
    once_node = _once_node(10, start=datetime.now(UTC) - timedelta(seconds=5))
    real_add_job = running_schedule_service.scheduler.add_job

    def failing_add_job(*args, **kwargs):
        raise RuntimeError("job store unavailable")

    monkeypatch.setattr(running_schedule_service.scheduler, "add_job", failing_add_job)
    await running_schedule_service.add_schedule(once_node)
    monkeypatch.setattr(running_schedule_service.scheduler, "add_job", real_add_job)
    running_schedule_service.repository = FakeScheduleRepository([once_node])

    await running_schedule_service.reconcile_schedules_with_db()

    published = await _published_actions(schedule_channel_subscription, timeout=1.5)
    assert {"action": "run_session", "node_id": 10} in published


@pytest.mark.asyncio
async def test_reconcile_leaves_jobs_untouched_when_db_unreadable(schedule_service):
    await schedule_service.add_schedule(_repeat_node(1))
    schedule_service.repository = FakeScheduleRepository(None)

    with pytest.raises(ScheduleSyncError):
        await schedule_service.reconcile_schedules_with_db()

    assert schedule_service.scheduler.get_job("schedule_1") is not None


@pytest.mark.asyncio
async def test_listener_resubscribes_after_pubsub_error_and_reconciles(no_reconnect_delay):
    flaky_client = FlakyPubSubRedis(failing_subscriptions=1)
    service = ScheduleService(redis_service=_redis_service_with(flaky_client))
    # Node 1 was deleted and node 2 created while the subscription was down.
    service.repository = FakeScheduleRepository([_repeat_node(1)], [_repeat_node(2)])

    await service.start()
    try:
        await _wait_until(lambda: service.scheduler.get_job("schedule_2") is not None)
        assert service.scheduler.get_job("schedule_1") is None
        assert flaky_client.subscription_count == 2

        # The new subscription receives live updates again.
        await flaky_client.publish(
            settings.SCHEDULE_CHANNEL, _node_update_message("create", _repeat_node(3))
        )
        await _wait_until(lambda: service.scheduler.get_job("schedule_3") is not None)
    finally:
        await _stop_listener_and_scheduler(service)
        await flaky_client.aclose()


@pytest.mark.asyncio
async def test_start_buffers_update_published_during_initial_load(redis_service):
    async def django_creates_node_2_during_load():
        await redis_service.aioredis_client.publish(
            settings.SCHEDULE_CHANNEL, _node_update_message("create", _repeat_node(2))
        )

    service = ScheduleService(redis_service=redis_service)
    # The empty second result would remove node 1 if the listener reconciled
    # needlessly on its first, already-synced subscription.
    service.repository = FakeScheduleRepository(
        [_repeat_node(1)], [], on_call=django_creates_node_2_during_load
    )

    await service.start()
    try:
        await _wait_until(lambda: service.scheduler.get_job("schedule_2") is not None)
        assert service.scheduler.get_job("schedule_1") is not None
        assert service.repository.calls == 1
    finally:
        await _stop_listener_and_scheduler(service)


@pytest.mark.asyncio
async def test_start_reconciles_once_listener_subscribes_after_initial_subscribe_failed(
    no_reconnect_delay,
):
    client = UnreachableAtFirstRedis()
    service = ScheduleService(redis_service=_redis_service_with(client))
    # Node 2 was created after the initial load, before anything was subscribed.
    service.repository = FakeScheduleRepository(
        [_repeat_node(1)], [_repeat_node(1), _repeat_node(2)]
    )

    await service.start()
    try:
        await _wait_until(lambda: service.scheduler.get_job("schedule_2") is not None)
        assert service.scheduler.get_job("schedule_1") is not None
        assert client.subscribe_attempts == 2
    finally:
        await _stop_listener_and_scheduler(service)
        await client.aclose()


@pytest.mark.asyncio
async def test_listener_retries_reconcile_while_db_is_down_with_warning_only(
    no_reconnect_delay, captured_logs
):
    flaky_client = FlakyPubSubRedis(failing_subscriptions=1)
    service = ScheduleService(redis_service=_redis_service_with(flaky_client))
    service.repository = FakeScheduleRepository([_repeat_node(1)], None, [_repeat_node(2)])

    await service.start()
    try:
        await _wait_until(lambda: service.scheduler.get_job("schedule_2") is not None)
    finally:
        await _stop_listener_and_scheduler(service)
        await flaky_client.aclose()

    reconcile_failures = [
        record for record in captured_logs if "Reconcile failed" in record["message"]
    ]
    assert [record["level"].name for record in reconcile_failures] == ["WARNING"]
    assert reconcile_failures[0]["exception"] is None


@pytest.mark.asyncio
async def test_initial_load_retries_until_db_is_readable(redis_service, no_reconnect_delay):
    service = ScheduleService(redis_service=redis_service)
    service.repository = FakeScheduleRepository(None, None, [_repeat_node(1)])

    await service.load_schedules_from_django()

    assert service.scheduler.get_job("schedule_1") is not None
    assert service.repository.calls == 3
