"""A 'deactivate' from the Manager switches a repeat schedule off only while it has no fire time left.

The Manager repeats the 'deactivate' it sends for a repeat schedule with no fire
time left before its end until the DB acknowledges it, so a copy can arrive after
the user extended the schedule. Such a stale copy leaves the node running. A
repeat node with no fire time left, or with its runs used up, is switched off; a
once-mode node is switched off after its run; an inactive or unknown node is left
as it is.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from tables.models.graph_models import ScheduleTriggerNode
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tests.schedule_channel_fixtures import *  # noqa: F401,F403
from tests.schedule_channel_fixtures import published_messages

START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _active_repeat_node(graph, **overrides) -> ScheduleTriggerNode:
    fields = {
        "graph": graph,
        "node_name": "repeat",
        "is_active": True,
        "run_mode": ScheduleTriggerNode.RunMode.REPEAT,
        "start_date_time": START,
        "every": 1,
        "unit": ScheduleTriggerNode.TimeUnit.HOURS,
        "end_type": ScheduleTriggerNode.EndType.ON_DATE,
        "end_date_time": START + timedelta(days=1),
        **overrides,
    }
    return ScheduleTriggerNode.objects.create(**fields)


def _extended_overrides() -> dict:
    end = datetime.now(UTC) + timedelta(days=30)
    return {"end_date_time": end, "next_run_date_time": end - timedelta(days=1)}


def _deactivate_message(node_id) -> dict:
    return {"data": json.dumps({"action": "deactivate", "node_id": node_id})}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "node_overrides",
    [
        {},
        {
            "end_type": ScheduleTriggerNode.EndType.AFTER_N_RUNS,
            "end_date_time": None,
            "max_runs": 3,
            "current_runs": 3,
        },
    ],
    ids=["end-passed", "runs-used-up"],
)
def test_deactivate_switches_off_a_repeat_node_with_no_fire_time_left(
    graph, manager_channel, django_capture_on_commit_callbacks, node_overrides
):
    node = _active_repeat_node(graph, **node_overrides)

    with django_capture_on_commit_callbacks(execute=True):
        ScheduleTriggerService().deactivate_node(node.id)

    node.refresh_from_db()
    assert node.is_active is False
    assert node.next_run_date_time is None
    # The Manager learns the node is off through the usual node_update echo.
    published = published_messages(manager_channel)
    assert [
        (message["data"]["action"], message["data"]["node"]["id"]) for message in published
    ] == [("update", node.id)]
    assert published[0]["data"]["node"]["is_active"] is False


@pytest.mark.django_db
def test_stale_deactivate_for_a_repeat_node_extended_since_leaves_it_running(
    graph, manager_channel, django_capture_on_commit_callbacks
):
    node = _active_repeat_node(graph, **_extended_overrides())
    before = ScheduleTriggerNode.objects.values().get(pk=node.pk)

    with django_capture_on_commit_callbacks(execute=True):
        ScheduleTriggerService().deactivate_node(node.id)

    assert ScheduleTriggerNode.objects.values().get(pk=node.pk) == before
    assert published_messages(manager_channel) == []


@pytest.mark.django_db
def test_deactivate_switches_off_a_once_mode_node_after_its_run(graph):
    # A once-mode trigger still reports its run time after the run, so the
    # fire-time check that guards repeat nodes must not apply here.
    node = ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="once",
        is_active=True,
        run_mode=ScheduleTriggerNode.RunMode.ONCE,
        start_date_time=START,
        end_type=ScheduleTriggerNode.EndType.NEVER,
        next_run_date_time=START,
    )

    ScheduleTriggerService().deactivate_node(node.id)

    node.refresh_from_db()
    assert node.is_active is False
    assert node.next_run_date_time is None


@pytest.mark.django_db
def test_deactivate_for_an_inactive_node_changes_nothing(
    graph, manager_channel, django_capture_on_commit_callbacks
):
    node = _active_repeat_node(graph, is_active=False)
    before = ScheduleTriggerNode.objects.values().get(pk=node.pk)

    with django_capture_on_commit_callbacks(execute=True):
        ScheduleTriggerService().deactivate_node(node.id)

    assert ScheduleTriggerNode.objects.values().get(pk=node.pk) == before
    assert published_messages(manager_channel) == []


@pytest.mark.django_db
def test_deactivate_for_an_unknown_node_is_ignored(manager_channel):
    ScheduleTriggerService().deactivate_node(999_999)

    assert published_messages(manager_channel) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("node_overrides", "still_active"),
    [({}, False), (_extended_overrides(), True)],
    ids=["no-fire-time-left", "extended-since"],
)
def test_schedule_channel_deactivate_message_respects_the_fire_times_left(
    graph, schedule_pubsub, node_overrides, still_active
):
    node = _active_repeat_node(graph, **node_overrides)

    schedule_pubsub.schedule_channel_handler(_deactivate_message(node.id))

    node.refresh_from_db()
    assert node.is_active is still_active
