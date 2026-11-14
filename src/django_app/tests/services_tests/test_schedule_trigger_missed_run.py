"""A once-mode schedule whose run the Manager missed is switched off and remembers when it was due.

The Manager reports the miss on the schedule channel and repeats it until the DB
acknowledges it, so applying it is idempotent and only ever applies to the exact
run that was missed: a node already off, no longer once-mode, or rescheduled to
another start is left untouched. The recorded time is cleared when the user
reactivates or reconfigures the schedule, and kept on edits that do not touch it.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import fakeredis
import pytest
from django.conf import settings

from tables.models.graph_models import ScheduleTriggerNode
from tables.services import redis_pubsub
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.signals import schedule_signals

MISSED_START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def manager_channel(monkeypatch):
    """Subscription to what Django publishes for the Manager on the schedule channel."""
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        schedule_signals, "RedisService", lambda: SimpleNamespace(redis_client=redis_client)
    )
    subscription = redis_client.pubsub()
    subscription.subscribe(settings.SCHEDULE_CHANNEL)
    # Consume the subscribe confirmation so only published messages remain.
    subscription.get_message(timeout=1)
    yield subscription
    subscription.close()


def _published(subscription) -> list[dict]:
    messages = []
    while (message := subscription.get_message(timeout=0.05)) is not None:
        messages.append(json.loads(message["data"]))
    return messages


@pytest.fixture
def schedule_pubsub(monkeypatch):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    # The handler calls close_old_connections(), which would drop the test's
    # transactional DB connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    yield redis_pubsub.RedisPubSub()


def _active_once_node(graph, start=MISSED_START, **overrides) -> ScheduleTriggerNode:
    fields = {
        "graph": graph,
        "node_name": "once",
        "is_active": True,
        "run_mode": ScheduleTriggerNode.RunMode.ONCE,
        "start_date_time": start,
        "end_type": ScheduleTriggerNode.EndType.NEVER,
        "next_run_date_time": start,
        **overrides,
    }
    return ScheduleTriggerNode.objects.create(**fields)


def _missed_message(node_id, **fields) -> dict:
    return {"data": json.dumps({"action": "missed", "node_id": node_id, **fields})}


@pytest.mark.django_db
def test_missed_run_switches_the_node_off_and_records_when_it_was_due(
    graph, manager_channel, django_capture_on_commit_callbacks
):
    node = _active_once_node(graph)

    with django_capture_on_commit_callbacks(execute=True):
        ScheduleTriggerService().mark_missed(node.id, MISSED_START)

    node.refresh_from_db()
    assert node.is_active is False
    assert node.next_run_date_time is None
    assert node.missed_run_at == MISSED_START
    # The Manager learns the node is off through the usual node_update echo.
    published = _published(manager_channel)
    assert [
        (message["data"]["action"], message["data"]["node"]["id"]) for message in published
    ] == [("update", node.id)]
    assert published[0]["data"]["node"]["is_active"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scheduled_at",
    [
        MISSED_START.astimezone(ZoneInfo("Europe/Kyiv")),
        MISSED_START.astimezone(ZoneInfo("America/New_York")),
    ],
    ids=["kyiv-offset", "new-york-offset"],
)
def test_missed_run_reported_in_another_offset_matches_the_same_instant(graph, scheduled_at):
    node = _active_once_node(graph)

    ScheduleTriggerService().mark_missed(node.id, scheduled_at)

    node.refresh_from_db()
    assert node.is_active is False
    assert node.missed_run_at == MISSED_START


@pytest.mark.django_db
@pytest.mark.parametrize(
    "node_overrides",
    [
        {"is_active": False, "next_run_date_time": None},
        {
            "run_mode": ScheduleTriggerNode.RunMode.REPEAT,
            "every": 1,
            "unit": ScheduleTriggerNode.TimeUnit.HOURS,
        },
        {"start_date_time": MISSED_START + timedelta(days=1)},
        {"start_date_time": MISSED_START + timedelta(microseconds=1)},
    ],
    ids=["already-inactive", "repeat-node", "rescheduled", "start-differs-by-a-microsecond"],
)
def test_missed_signal_for_a_run_the_node_no_longer_has_changes_nothing(
    graph, manager_channel, django_capture_on_commit_callbacks, node_overrides
):
    node = _active_once_node(graph, **node_overrides)
    before = ScheduleTriggerNode.objects.values().get(pk=node.pk)

    with django_capture_on_commit_callbacks(execute=True):
        ScheduleTriggerService().mark_missed(node.id, MISSED_START)

    assert ScheduleTriggerNode.objects.values().get(pk=node.pk) == before
    assert _published(manager_channel) == []


@pytest.mark.django_db
def test_missed_signal_for_an_unknown_node_is_ignored(manager_channel):
    ScheduleTriggerService().mark_missed(999_999, MISSED_START)

    assert _published(manager_channel) == []


@pytest.mark.django_db
def test_repeated_missed_signal_keeps_the_first_result(graph):
    node = _active_once_node(graph)

    ScheduleTriggerService().mark_missed(node.id, MISSED_START)
    after_first = ScheduleTriggerNode.objects.values().get(pk=node.pk)
    ScheduleTriggerService().mark_missed(node.id, MISSED_START)

    assert ScheduleTriggerNode.objects.values().get(pk=node.pk) == after_first


@pytest.mark.django_db
@pytest.mark.parametrize(
    "start",
    [MISSED_START, MISSED_START.replace(microsecond=123456)],
    ids=["whole-seconds", "with-microseconds"],
)
def test_schedule_channel_missed_message_switches_the_node_off(graph, schedule_pubsub, start):
    node = _active_once_node(graph, start=start)

    # The Manager sends the run time as an ISO 8601 UTC string.
    schedule_pubsub.schedule_channel_handler(
        _missed_message(node.id, scheduled_at=start.isoformat())
    )

    node.refresh_from_db()
    assert node.is_active is False
    assert node.missed_run_at == start


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"scheduled_at": None},
        {"scheduled_at": "not-a-date"},
        {"scheduled_at": "2026-11-10T09:00:00"},
    ],
    ids=["missing", "null", "unparseable", "no-timezone"],
)
def test_schedule_channel_missed_message_without_a_usable_time_changes_nothing(
    graph, schedule_pubsub, fields
):
    node = _active_once_node(graph)
    before = ScheduleTriggerNode.objects.values().get(pk=node.pk)

    schedule_pubsub.schedule_channel_handler(_missed_message(node.id, **fields))

    assert ScheduleTriggerNode.objects.values().get(pk=node.pk) == before


def _missed_once_node(graph) -> ScheduleTriggerNode:
    return _active_once_node(
        graph, is_active=False, next_run_date_time=None, missed_run_at=MISSED_START
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"is_active": True, "start_date_time": datetime.now(UTC) + timedelta(days=1)},
        {"is_active": True},
        {"run_mode": ScheduleTriggerNode.RunMode.REPEAT},
        {"timezone": "Europe/Kyiv"},
        {"start_date_time": MISSED_START + timedelta(days=1)},
        {"every": 2},
        {"unit": ScheduleTriggerNode.TimeUnit.HOURS},
        {"weekdays": ["mon"]},
        {"end_type": ScheduleTriggerNode.EndType.ON_DATE},
        {"end_date_time": MISSED_START + timedelta(days=2)},
        {"max_runs": 3},
    ],
    ids=lambda change: "+".join(change),
)
def test_reactivating_or_reconfiguring_the_schedule_clears_the_missed_run(graph, change):
    node = _missed_once_node(graph)

    ScheduleTriggerService().update_node(node, dict(change))

    node.refresh_from_db()
    assert node.missed_run_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        {"node_name": "renamed"},
        {"metadata": {"position": {"x": 10, "y": 20}}},
        # The editor re-sends the unchanged schedule along with a rename.
        {
            "node_name": "renamed",
            "run_mode": ScheduleTriggerNode.RunMode.ONCE,
            "timezone": "UTC",
            "start_date_time": MISSED_START,
            "every": None,
            "unit": None,
            "weekdays": None,
            "end_type": ScheduleTriggerNode.EndType.NEVER,
            "end_date_time": None,
            "max_runs": None,
        },
    ],
    ids=["rename", "move", "rename-with-unchanged-schedule"],
)
def test_edit_that_leaves_the_schedule_as_it_was_keeps_the_missed_run(graph, change):
    node = _missed_once_node(graph)

    ScheduleTriggerService().update_node(node, dict(change))

    node.refresh_from_db()
    assert node.missed_run_at == MISSED_START


@pytest.mark.django_db
def test_recording_a_missed_run_alone_does_not_change_the_content_hash(graph):
    node = _missed_once_node(graph)
    hash_with_missed_run = node.generate_hash()

    node.missed_run_at = None

    assert node.generate_hash() == hash_with_missed_run
