import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import settings
from apscheduler.events import EVENT_JOB_MISSED
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


def _scheduled_nodes(service: ScheduleService) -> dict[int, ScheduleTriggerNodePayload]:
    return {job.args[0].id: job.args[0] for job in service.scheduler.get_jobs()}


async def _stop_listener_and_scheduler(service: ScheduleService):
    background_tasks = [service.listener_task, service.pending_signal_retry_task]
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
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

    assert 1 not in _scheduled_nodes(schedule_service)
    assert 2 in _scheduled_nodes(schedule_service)
    assert 3 in _scheduled_nodes(schedule_service)
    assert await _published_actions(schedule_channel_subscription) == []


@pytest.mark.asyncio
async def test_reconcile_replaces_job_whose_node_changed(schedule_service):
    await schedule_service.add_schedule(_repeat_node(1, every=1))
    schedule_service.repository = FakeScheduleRepository([_repeat_node(1, every=6)])

    await schedule_service.reconcile_schedules_with_db()

    assert _scheduled_nodes(schedule_service)[1].every == 6


@pytest.mark.asyncio
async def test_reconcile_does_not_re_add_once_node_that_already_fired(
    running_schedule_service, schedule_channel_subscription
):
    once_node = _once_node(7, start=datetime.now(UTC) - timedelta(seconds=1))
    await running_schedule_service.add_schedule(once_node)
    first_fire = await _published_actions(schedule_channel_subscription, timeout=1.5)
    assert first_fire == [
        {"action": "run_session", "node_id": 7},
        {"action": "deactivate", "node_id": 7},
    ]
    # Django has not processed the 'deactivate' yet, so the node is still active.
    future_once_node = _once_node(8, start=datetime.now(UTC) + timedelta(hours=1))
    running_schedule_service.repository = FakeScheduleRepository([once_node, future_once_node])

    await running_schedule_service.reconcile_schedules_with_db()

    assert 7 not in _scheduled_nodes(running_schedule_service)
    assert 8 in _scheduled_nodes(running_schedule_service)
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

    assert 1 in _scheduled_nodes(schedule_service)


@pytest.mark.asyncio
async def test_listener_resubscribes_after_pubsub_error_and_reconciles(no_reconnect_delay):
    flaky_client = FlakyPubSubRedis(failing_subscriptions=1)
    service = ScheduleService(redis_service=_redis_service_with(flaky_client))
    # Node 1 was deleted and node 2 created while the subscription was down.
    service.repository = FakeScheduleRepository([_repeat_node(1)], [_repeat_node(2)])

    await service.start()
    try:
        await _wait_until(lambda: 2 in _scheduled_nodes(service))
        assert 1 not in _scheduled_nodes(service)

        # The new subscription receives live updates again.
        await flaky_client.publish(
            settings.SCHEDULE_CHANNEL, _node_update_message("create", _repeat_node(3))
        )
        await _wait_until(lambda: 3 in _scheduled_nodes(service))
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
        await _wait_until(lambda: 2 in _scheduled_nodes(service))
        assert 1 in _scheduled_nodes(service)
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
        await _wait_until(lambda: 2 in _scheduled_nodes(service))
        assert 1 in _scheduled_nodes(service)
    finally:
        await _stop_listener_and_scheduler(service)
        await client.aclose()


@pytest.mark.asyncio
async def test_listener_retries_reconcile_while_db_is_down(no_reconnect_delay):
    flaky_client = FlakyPubSubRedis(failing_subscriptions=1)
    service = ScheduleService(redis_service=_redis_service_with(flaky_client))
    service.repository = FakeScheduleRepository([_repeat_node(1)], None, [_repeat_node(2)])

    await service.start()
    try:
        await _wait_until(lambda: 2 in _scheduled_nodes(service))
    finally:
        await _stop_listener_and_scheduler(service)
        await flaky_client.aclose()


@pytest.mark.asyncio
async def test_initial_load_retries_until_db_is_readable(redis_service, no_reconnect_delay):
    service = ScheduleService(redis_service=redis_service)
    service.repository = FakeScheduleRepository(None, None, [_repeat_node(1)])

    await service.load_schedules_from_django()

    assert 1 in _scheduled_nodes(service)


@pytest.mark.asyncio
async def test_live_updates_from_django_add_pause_and_delete_schedules(
    redis_service, schedule_channel_subscription
):
    service = ScheduleService(redis_service=redis_service)
    service.repository = FakeScheduleRepository([])
    client = redis_service.aioredis_client
    await service.start()
    try:
        await client.publish(settings.SCHEDULE_CHANNEL, _node_update_message("create", _repeat_node(1)))
        await client.publish(settings.SCHEDULE_CHANNEL, _node_update_message("create", _repeat_node(2)))
        await _wait_until(lambda: set(_scheduled_nodes(service)) == {1, 2})

        paused_node = _repeat_node(1).model_copy(update={"is_active": False})
        await client.publish(settings.SCHEDULE_CHANNEL, _node_update_message("update", paused_node))
        await client.publish(
            settings.SCHEDULE_CHANNEL,
            json.dumps({"action": "node_update", "data": {"action": "delete", "node": {"id": 2}}}),
        )
        await _wait_until(lambda: _scheduled_nodes(service) == {})
    finally:
        await _stop_listener_and_scheduler(service)

    # Django already knows these nodes are inactive or deleted: no 'deactivate' back.
    published = await _published_actions(schedule_channel_subscription)
    assert [message for message in published if message.get("action") == "deactivate"] == []


@pytest.mark.asyncio
async def test_repeat_schedule_publishes_deactivate_once_its_end_date_passes(
    running_schedule_service, schedule_channel_subscription
):
    now = datetime.now(UTC)
    ending_node = ScheduleTriggerNodePayload(
        id=11,
        node_name="ending",
        graph=1,
        is_active=True,
        run_mode="repeat",
        start_date_time=now,
        every=1,
        unit="seconds",
        end_type="on_date",
        end_date_time=now + timedelta(seconds=1.5),
    )

    await running_schedule_service.add_schedule(ending_node)

    published = await _published_actions(schedule_channel_subscription, timeout=3)
    assert {"action": "run_session", "node_id": 11} in published
    assert published[-1] == {"action": "deactivate", "node_id": 11}
    assert published.count({"action": "deactivate", "node_id": 11}) == 1


# A once-mode run whose start passed more than the 30 s misfire grace while the
# Manager was down is skipped by APScheduler. Django must hear about it as a
# 'missed' signal, repeated until the DB shows it was applied, so the node does
# not stay active forever without ever running.

MISFIRE_GRACE = timedelta(seconds=30)
# Published by a test at a phase boundary: everything after it on the channel
# was published after that boundary. The service ignores it like any other
# non-node_update message.
PHASE_MARKER = {"action": "test_phase_marker"}


def _missed_signal(node_id: int, scheduled_at: datetime) -> dict:
    return {"action": "missed", "node_id": node_id, "scheduled_at": scheduled_at.isoformat()}


def _start_beyond_misfire_grace() -> datetime:
    return (datetime.now(UTC) - MISFIRE_GRACE - timedelta(minutes=2)).replace(microsecond=0)


def _missed_node_ids(actions: list[dict]) -> list[int]:
    return [action["node_id"] for action in actions if action["action"] == "missed"]


def _includes_missed_of(*node_ids: int):
    return lambda actions: set(node_ids) <= set(_missed_node_ids(actions))


async def _read_actions_until(subscription, condition, timeout: float = 2.0) -> list[dict]:
    """Read published actions until condition(actions read so far) holds.

    The timeout only bounds a failing test; a passing one returns as soon as the
    condition holds.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    actions = []
    while not condition(actions):
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(f"condition not met in time; actions read: {actions}")
        message = await subscription.get_message(
            ignore_subscribe_messages=True, timeout=min(remaining, 0.05)
        )
        if message is not None:
            actions.append(json.loads(message["data"]))
    return actions


async def _drain_actions(subscription) -> list[dict]:
    """Return every action already delivered to the subscription, without waiting."""
    actions = []
    while (
        message := await subscription.get_message(ignore_subscribe_messages=True, timeout=0)
    ) is not None:
        actions.append(json.loads(message["data"]))
    return actions


async def _publish_phase_marker(redis_service: RedisService):
    await redis_service.aioredis_client.publish(settings.SCHEDULE_CHANNEL, json.dumps(PHASE_MARKER))


def _split_at_phase_markers(actions: list[dict]) -> list[list[dict]]:
    phases = [[]]
    for action in actions:
        if action == PHASE_MARKER:
            phases.append([])
        else:
            phases[-1].append(action)
    return phases


async def _wait_for_complete_retry_ticks(repository: FakeScheduleRepository, count: int):
    """Wait until count retry ticks have both started and finished after this call.

    Each tick reads the repository once and the ticks run one after another, so
    tick N has finished once tick N + 1 reads the repository. Only usable while
    a signal is pending: a tick with nothing pending reads nothing.
    """
    calls_before = repository.calls
    await _wait_until(lambda: repository.calls >= calls_before + count + 1)


async def _start_with_missed_once_nodes(
    service: ScheduleService, subscription, *once_nodes: ScheduleTriggerNodePayload
):
    """Start the service on a DB holding once-nodes whose runs were missed."""
    service.repository = FakeScheduleRepository(list(once_nodes))
    await service.start()
    published = await _read_actions_until(
        subscription, _includes_missed_of(*(node.id for node in once_nodes))
    )
    for node in once_nodes:
        assert _missed_signal(node.id, node.start_date_time) in published


def _ended_repeat_node(
    node_id: int,
    unit: str = "minutes",
    every: int = 1,
    start: datetime | None = None,
    end: datetime | None = None,
) -> ScheduleTriggerNodePayload:
    """A repeat node whose end, by default, passed while the Manager was down."""
    now = datetime.now(UTC).replace(microsecond=0)
    return ScheduleTriggerNodePayload(
        id=node_id,
        node_name=f"ended-{node_id}",
        graph=1,
        is_active=True,
        run_mode="repeat",
        start_date_time=start or now - timedelta(hours=1),
        every=every,
        unit=unit,
        end_type="on_date",
        end_date_time=end or now - timedelta(minutes=1),
    )


def _deactivate_signal(node_id: int) -> dict:
    return {"action": "deactivate", "node_id": node_id}


def _deactivated_node_ids(actions: list[dict]) -> list[int]:
    return [action["node_id"] for action in actions if action["action"] == "deactivate"]


def _includes_deactivate_of(*node_ids: int):
    return lambda actions: set(node_ids) <= set(_deactivated_node_ids(actions))


async def _start_with_ended_repeat_nodes(
    service: ScheduleService, subscription, *ended_nodes: ScheduleTriggerNodePayload
):
    """Start the service on a DB that still shows ended repeat nodes as active."""
    service.repository = FakeScheduleRepository(list(ended_nodes))
    await service.start()
    published = await _read_actions_until(
        subscription, _includes_deactivate_of(*(node.id for node in ended_nodes))
    )
    for node in ended_nodes:
        assert _deactivate_signal(node.id) in published


@pytest_asyncio.fixture
async def unstarted_schedule_service(redis_service):
    service = ScheduleService(redis_service=redis_service)
    yield service
    if service.scheduler.running:
        service.scheduler.shutdown(wait=False)


@pytest.fixture
def republish_logs():
    records = []
    handler_id = logger.add(
        lambda message: records.append(message.record["level"].name),
        level="DEBUG",
        filter=lambda record: "; republishing '" in record["message"],
    )
    yield records
    logger.remove(handler_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start_age", "expected_actions"),
    [
        (timedelta(seconds=5), ["run_session", "deactivate"]),
        (MISFIRE_GRACE + timedelta(minutes=2), ["missed"]),
    ],
    ids=["within-misfire-grace-runs", "beyond-misfire-grace-is-missed"],
)
async def test_once_node_registered_before_scheduler_start_runs_or_reports_missed(
    unstarted_schedule_service, schedule_channel_subscription, start_age, expected_actions
):
    start = (datetime.now(UTC) - start_age).replace(microsecond=0)
    # The order ScheduleService.start uses: load nodes from the DB, then start APScheduler.
    await unstarted_schedule_service.add_schedule(_once_node(20, start))
    unstarted_schedule_service.scheduler.start()

    published = await _published_actions(schedule_channel_subscription, timeout=1.0)

    assert [message["action"] for message in published] == expected_actions


@pytest.mark.asyncio
async def test_missed_once_run_reports_its_scheduled_time_in_utc(
    unstarted_schedule_service, schedule_channel_subscription
):
    start = _start_beyond_misfire_grace()
    await unstarted_schedule_service.add_schedule(_once_node(21, start))
    unstarted_schedule_service.scheduler.start()

    published = await _published_actions(schedule_channel_subscription, timeout=1.0)

    assert published == [_missed_signal(21, start)]
    assert published[0]["scheduled_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_missed_ticks_of_a_repeat_schedule_are_not_reported(
    schedule_service, schedule_channel_subscription
):
    missed_job_ids = []
    schedule_service.scheduler.add_listener(
        lambda event: missed_job_ids.append(event.job_id), EVENT_JOB_MISSED
    )
    overdue_tick = _start_beyond_misfire_grace()
    await schedule_service.add_schedule(_repeat_node(22))
    # The event loop was blocked past the tick, as on a suspended host.
    schedule_service.scheduler.modify_job("schedule_22", next_run_time=overdue_tick)
    # Due later than node 22's tick, so APScheduler handles it after that tick:
    # its 'missed' signal arrives after anything node 22 would have published.
    later_missed_once_node = _once_node(32, overdue_tick + timedelta(seconds=10))
    await schedule_service.add_schedule(later_missed_once_node)

    schedule_service.scheduler.resume()
    published = await _read_actions_until(schedule_channel_subscription, _includes_missed_of(32))

    assert missed_job_ids == ["schedule_22", "schedule_32"]
    assert published == [_missed_signal(32, later_missed_once_node.start_date_time)]
    assert 22 in _scheduled_nodes(schedule_service)


@pytest.mark.asyncio
async def test_once_node_removed_before_its_run_is_processed_reports_nothing(
    schedule_service, schedule_channel_subscription
):
    start = _start_beyond_misfire_grace()
    await schedule_service.add_schedule(_once_node(23, start))
    # Due later than node 23, so its 'missed' signal arrives after anything
    # node 23 would have published.
    later_missed_once_node = _once_node(33, start + timedelta(seconds=10))
    await schedule_service.add_schedule(later_missed_once_node)
    await schedule_service.remove_schedule(23)

    schedule_service.scheduler.resume()
    published = await _read_actions_until(schedule_channel_subscription, _includes_missed_of(33))

    assert published == [_missed_signal(33, later_missed_once_node.start_date_time)]


@pytest.mark.asyncio
async def test_reconcile_after_a_missed_once_run_does_not_schedule_it_again(
    unstarted_schedule_service, schedule_channel_subscription
):
    once_node = _once_node(24, _start_beyond_misfire_grace())
    await unstarted_schedule_service.add_schedule(once_node)
    unstarted_schedule_service.scheduler.start()
    assert await _read_actions_until(schedule_channel_subscription, _includes_missed_of(24)) == [
        _missed_signal(24, once_node.start_date_time)
    ]
    # Django has not applied the 'missed' signal yet, so the node is still active.
    unstarted_schedule_service.repository = FakeScheduleRepository([once_node])

    await unstarted_schedule_service.reconcile_schedules_with_db()

    assert 24 not in _scheduled_nodes(unstarted_schedule_service)
    # A job re-added for node 24 is due earlier than this one, so APScheduler
    # would report it again before this node's 'missed' signal.
    later_missed_once_node = _once_node(34, once_node.start_date_time + timedelta(seconds=10))
    await unstarted_schedule_service.add_schedule(later_missed_once_node)
    assert await _read_actions_until(schedule_channel_subscription, _includes_missed_of(34)) == [
        _missed_signal(34, later_missed_once_node.start_date_time)
    ]


@pytest.mark.asyncio
async def test_missed_signal_is_repeated_while_the_db_still_shows_the_node_active(
    redis_service, schedule_channel_subscription, no_reconnect_delay
):
    once_node = _once_node(25, _start_beyond_misfire_grace())
    service = ScheduleService(redis_service=redis_service)
    try:
        await _start_with_missed_once_nodes(service, schedule_channel_subscription, once_node)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(service.repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, republished = _split_at_phase_markers(await _drain_actions(schedule_channel_subscription))
    assert len(republished) >= 2
    assert all(message == _missed_signal(25, once_node.start_date_time) for message in republished)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "db_state_after_miss",
    [
        lambda node: [],
        lambda node: [
            node.model_copy(update={"start_date_time": node.start_date_time + timedelta(days=1)})
        ],
        lambda node: [_repeat_node(node.id)],
    ],
    ids=["switched-off-or-deleted", "start-changed", "switched-to-repeat"],
)
async def test_missed_signal_stops_once_the_db_no_longer_shows_that_run(
    redis_service, schedule_channel_subscription, no_reconnect_delay, db_state_after_miss
):
    once_node = _once_node(26, _start_beyond_misfire_grace())
    # Stays unacknowledged, so the retry loop keeps reading the DB and publishing.
    still_missed_node = _once_node(36, once_node.start_date_time + timedelta(seconds=10))
    service = ScheduleService(redis_service=redis_service)
    try:
        await _start_with_missed_once_nodes(
            service, schedule_channel_subscription, once_node, still_missed_node
        )
        settled_repository = FakeScheduleRepository(
            [*db_state_after_miss(once_node), still_missed_node]
        )
        service.repository = settled_repository
        # Ticks that read the previous DB state have finished once the new one is read.
        await _wait_until(lambda: settled_repository.calls >= 1)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(settled_repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, after_db_settled = _split_at_phase_markers(
        await _drain_actions(schedule_channel_subscription)
    )
    assert 36 in _missed_node_ids(after_db_settled)
    assert 26 not in _missed_node_ids(after_db_settled)


@pytest.mark.asyncio
async def test_missed_signal_survives_an_unreadable_db_and_is_repeated_once_readable(
    redis_service, schedule_channel_subscription, no_reconnect_delay
):
    once_node = _once_node(27, _start_beyond_misfire_grace())
    service = ScheduleService(redis_service=redis_service)
    try:
        await _start_with_missed_once_nodes(service, schedule_channel_subscription, once_node)
        unreadable_repository = FakeScheduleRepository(None)
        service.repository = unreadable_repository
        await _wait_until(lambda: unreadable_repository.calls >= 1)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(unreadable_repository, 2)
        await _publish_phase_marker(redis_service)
        readable_repository = FakeScheduleRepository([once_node])
        service.repository = readable_repository
        await _wait_for_complete_retry_ticks(readable_repository, 1)
    finally:
        await _stop_listener_and_scheduler(service)

    _, while_unreadable, once_readable = _split_at_phase_markers(
        await _drain_actions(schedule_channel_subscription)
    )
    assert while_unreadable == []
    assert _missed_signal(27, once_node.start_date_time) in once_readable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("django_update", "update_applied"),
    [
        (
            lambda node: _node_update_message(
                "update",
                node.model_copy(update={"start_date_time": datetime.now(UTC) + timedelta(hours=1)}),
            ),
            # APScheduler removed the missed run's job; the update registers a new one.
            lambda service, node: node.id in _scheduled_nodes(service),
        ),
        (
            lambda node: _node_update_message(
                "update", node.model_copy(update={"is_active": False})
            ),
            lambda service, node: node.id not in service.schedule_nodes,
        ),
        (
            lambda node: json.dumps(
                {"action": "node_update", "data": {"action": "delete", "node": {"id": node.id}}}
            ),
            lambda service, node: node.id not in service.schedule_nodes,
        ),
    ],
    ids=["rescheduled", "switched-off", "deleted"],
)
async def test_node_update_from_django_stops_the_missed_signal_even_before_the_db_shows_it(
    redis_service, schedule_channel_subscription, no_reconnect_delay, django_update, update_applied
):
    once_node = _once_node(28, _start_beyond_misfire_grace())
    # Stays unacknowledged, so the retry loop keeps reading the DB and publishing.
    still_missed_node = _once_node(38, once_node.start_date_time + timedelta(seconds=10))
    service = ScheduleService(redis_service=redis_service)
    try:
        # The DB read keeps returning both nodes as they were when the runs were missed.
        await _start_with_missed_once_nodes(
            service, schedule_channel_subscription, once_node, still_missed_node
        )
        await redis_service.aioredis_client.publish(
            settings.SCHEDULE_CHANNEL, django_update(once_node)
        )
        await _wait_until(lambda: update_applied(service, once_node))
        # A tick that checked node 28 before the update arrived may still be publishing.
        await _wait_for_complete_retry_ticks(service.repository, 1)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(service.repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, after_update = _split_at_phase_markers(await _drain_actions(schedule_channel_subscription))
    assert 38 in _missed_node_ids(after_update)
    assert 28 not in _missed_node_ids(after_update)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pending_node", "start_with_pending_signal"),
    [
        (lambda: _once_node(29, _start_beyond_misfire_grace()), _start_with_missed_once_nodes),
        (lambda: _ended_repeat_node(39), _start_with_ended_repeat_nodes),
    ],
    ids=["missed", "deactivate"],
)
async def test_first_republish_of_a_pending_signal_logs_at_info_and_later_ones_at_debug(
    redis_service,
    schedule_channel_subscription,
    no_reconnect_delay,
    republish_logs,
    pending_node,
    start_with_pending_signal,
):
    service = ScheduleService(redis_service=redis_service)
    try:
        await start_with_pending_signal(service, schedule_channel_subscription, pending_node())
        await _wait_until(lambda: len(republish_logs) >= 3)
    finally:
        await _stop_listener_and_scheduler(service)

    assert republish_logs[0] == "INFO"
    assert set(republish_logs[1:]) == {"DEBUG"}


# A repeat schedule's end can pass while the Manager is down. APScheduler would
# store such a job paused, without any event, so the node would stay active
# forever. The Manager switches it off with a 'deactivate' instead, repeated
# until the DB shows it was applied, like an end reached while it runs.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unit", "every", "start_from_now", "end_from_now"),
    [
        ("seconds", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        ("minutes", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        ("hours", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        ("days", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        ("days", 2, -timedelta(hours=1), -timedelta(minutes=1)),
        ("weeks", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        ("weeks", 2, -timedelta(hours=1), -timedelta(minutes=1)),
        ("months", 1, -timedelta(hours=1), -timedelta(minutes=1)),
        # Next weekly match is six days away, after an end that is still ahead.
        ("weeks", 1, -timedelta(days=1), timedelta(days=3)),
    ],
    ids=[
        "seconds-interval-end-passed",
        "minutes-interval-end-passed",
        "hours-interval-end-passed",
        "daily-cron-end-passed",
        "days-interval-end-passed",
        "weekly-cron-end-passed",
        "every-other-week-cron-end-passed",
        "monthly-cron-end-passed",
        "weekly-cron-next-match-after-future-end",
    ],
)
async def test_repeat_schedule_without_a_fire_time_left_at_startup_is_switched_off(
    unstarted_schedule_service,
    schedule_channel_subscription,
    unit,
    every,
    start_from_now,
    end_from_now,
):
    now = datetime.now(UTC).replace(microsecond=0)
    node = _ended_repeat_node(
        40, unit=unit, every=every, start=now + start_from_now, end=now + end_from_now
    )
    # The order ScheduleService.start uses: load nodes from the DB, then start APScheduler.
    await unstarted_schedule_service.add_schedule(node)
    unstarted_schedule_service.scheduler.start()

    published = await _read_actions_until(schedule_channel_subscription, _includes_deactivate_of(40))

    assert published == [_deactivate_signal(40)]
    assert _scheduled_nodes(unstarted_schedule_service) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("end_after_last_fire", "registered"),
    [(timedelta(0), True), (-timedelta(seconds=1), False)],
    ids=["end-at-the-fire-time", "end-just-before-it"],
)
async def test_repeat_schedule_is_registered_only_while_a_fire_time_is_on_or_before_its_end(
    schedule_service, end_after_last_fire, registered
):
    only_fire_time = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0)
    node = _ended_repeat_node(
        41, every=5, start=only_fire_time, end=only_fire_time + end_after_last_fire
    )

    await schedule_service.add_schedule(node)

    assert (41 in _scheduled_nodes(schedule_service)) is registered


@pytest.mark.asyncio
async def test_update_leaving_a_live_schedule_without_a_fire_time_removes_its_job_and_switches_it_off(
    schedule_service, schedule_channel_subscription
):
    now = datetime.now(UTC).replace(microsecond=0)
    live_node = _ended_repeat_node(42, end=now + timedelta(hours=1))
    await schedule_service.add_schedule(live_node)

    await schedule_service.add_schedule(
        live_node.model_copy(update={"end_date_time": now - timedelta(minutes=1)})
    )

    assert await _published_actions(schedule_channel_subscription) == [_deactivate_signal(42)]
    assert 42 not in _scheduled_nodes(schedule_service)


@pytest.mark.asyncio
async def test_deactivate_for_an_end_reached_while_running_is_repeated_until_acknowledged(
    redis_service, schedule_channel_subscription, no_reconnect_delay
):
    now = datetime.now(UTC)
    ending_node = _ended_repeat_node(
        43, unit="seconds", start=now - timedelta(seconds=10), end=now + timedelta(seconds=1)
    )
    service = ScheduleService(redis_service=redis_service)
    # The DB keeps showing the node active: Django has not applied the signal.
    service.repository = FakeScheduleRepository([ending_node])
    try:
        await service.start()
        await _read_actions_until(
            schedule_channel_subscription, _includes_deactivate_of(43), timeout=3.0
        )
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(service.repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, republished = _split_at_phase_markers(await _drain_actions(schedule_channel_subscription))
    assert len(republished) >= 2
    assert all(message == _deactivate_signal(43) for message in republished)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "db_state_after_signal",
    [
        lambda node: [],
        lambda node: [
            node.model_copy(update={"end_date_time": datetime.now(UTC) + timedelta(days=1)})
        ],
    ],
    ids=["switched-off-or-deleted", "end-extended"],
)
async def test_deactivate_signal_stops_once_the_db_no_longer_needs_it(
    redis_service, schedule_channel_subscription, no_reconnect_delay, db_state_after_signal
):
    ended_node = _ended_repeat_node(44)
    # Stays unacknowledged, so the retry loop keeps reading the DB and publishing.
    still_ended_node = _ended_repeat_node(54)
    service = ScheduleService(redis_service=redis_service)
    try:
        await _start_with_ended_repeat_nodes(
            service, schedule_channel_subscription, ended_node, still_ended_node
        )
        settled_repository = FakeScheduleRepository(
            [*db_state_after_signal(ended_node), still_ended_node]
        )
        service.repository = settled_repository
        # Ticks that read the previous DB state have finished once the new one is read.
        await _wait_until(lambda: settled_repository.calls >= 1)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(settled_repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, after_db_settled = _split_at_phase_markers(
        await _drain_actions(schedule_channel_subscription)
    )
    assert 54 in _deactivated_node_ids(after_db_settled)
    assert 44 not in _deactivated_node_ids(after_db_settled)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("django_update", "update_applied"),
    [
        (
            lambda node: _node_update_message(
                "update",
                node.model_copy(update={"end_date_time": datetime.now(UTC) + timedelta(days=1)}),
            ),
            lambda service, node: node.id in _scheduled_nodes(service),
        ),
        (
            lambda node: _node_update_message(
                "update", node.model_copy(update={"is_active": False})
            ),
            lambda service, node: node.id not in service._pending_signals,
        ),
        (
            lambda node: json.dumps(
                {"action": "node_update", "data": {"action": "delete", "node": {"id": node.id}}}
            ),
            lambda service, node: node.id not in service._pending_signals,
        ),
    ],
    ids=["end-extended", "switched-off", "deleted"],
)
async def test_node_update_from_django_stops_the_deactivate_signal_even_before_the_db_shows_it(
    redis_service, schedule_channel_subscription, no_reconnect_delay, django_update, update_applied
):
    ended_node = _ended_repeat_node(45)
    # Stays unacknowledged, so the retry loop keeps reading the DB and publishing.
    still_ended_node = _ended_repeat_node(55)
    service = ScheduleService(redis_service=redis_service)
    try:
        # The DB read keeps returning both nodes as they were when they ended.
        await _start_with_ended_repeat_nodes(
            service, schedule_channel_subscription, ended_node, still_ended_node
        )
        await redis_service.aioredis_client.publish(
            settings.SCHEDULE_CHANNEL, django_update(ended_node)
        )
        await _wait_until(lambda: update_applied(service, ended_node))
        # A tick that checked node 45 before the update arrived may still be publishing.
        await _wait_for_complete_retry_ticks(service.repository, 1)
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(service.repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    _, after_update = _split_at_phase_markers(await _drain_actions(schedule_channel_subscription))
    assert 55 in _deactivated_node_ids(after_update)
    assert 45 not in _deactivated_node_ids(after_update)


@pytest.fixture
def warning_logs():
    records = []
    handler_id = logger.add(
        lambda message: records.append(message.record["message"]), level="WARNING"
    )
    yield records
    logger.remove(handler_id)


@pytest.mark.asyncio
async def test_reconcile_while_a_deactivate_is_pending_publishes_and_warns_nothing_more(
    schedule_service, schedule_channel_subscription, warning_logs
):
    ended_node = _ended_repeat_node(46)
    await schedule_service.add_schedule(ended_node)
    assert await _read_actions_until(
        schedule_channel_subscription, _includes_deactivate_of(46)
    ) == [_deactivate_signal(46)]
    # Django has not applied the signal yet, so the node is still active.
    schedule_service.repository = FakeScheduleRepository([ended_node])
    warning_logs.clear()

    await schedule_service.reconcile_schedules_with_db()

    assert await _published_actions(schedule_channel_subscription) == []
    assert warning_logs == []
    assert 46 not in _scheduled_nodes(schedule_service)


@pytest.mark.asyncio
async def test_deactivate_after_a_once_mode_run_is_published_once_not_repeated(
    redis_service, schedule_channel_subscription, no_reconnect_delay
):
    fired_node = _once_node(47, (datetime.now(UTC) - timedelta(seconds=5)).replace(microsecond=0))
    # Stays unacknowledged, so the retry loop keeps reading the DB and publishing.
    missed_node = _once_node(57, _start_beyond_misfire_grace())
    service = ScheduleService(redis_service=redis_service)
    # The DB keeps showing the fired node active, as if Django had not applied it yet.
    service.repository = FakeScheduleRepository([fired_node, missed_node])
    try:
        await service.start()
        published = await _read_actions_until(
            schedule_channel_subscription,
            lambda actions: 47 in _deactivated_node_ids(actions) and 57 in _missed_node_ids(actions),
        )
        await _publish_phase_marker(redis_service)
        await _wait_for_complete_retry_ticks(service.repository, 2)
    finally:
        await _stop_listener_and_scheduler(service)

    assert {"action": "run_session", "node_id": 47} in published
    _, after_run = _split_at_phase_markers(await _drain_actions(schedule_channel_subscription))
    assert 57 in _missed_node_ids(after_run)
    assert all(action["node_id"] != 47 for action in after_run)
