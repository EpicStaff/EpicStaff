"""Regression tests for out-of-band DB writers: something outside the
collaborative op channel (the scheduler process, an ORM cascade delete)
mutates the DB directly, and the live Redis snapshot + channel-layer
broadcast must still stay in sync with it.
"""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.flush_service import FlushStatus, GraphFlushService
from tables.graph_collab.groups import graph_group_name
from tables.models.crew_models import Crew
from tables.models.graph_models import CrewNode, ScheduleTriggerNode

from tests.graph_collab.conftest import _drain_connect, _make_communicator, get_node


# ---------------------------------------------------------------------------
# Scheduler deactivation — helpers
# ---------------------------------------------------------------------------


@sync_to_async
def _create_schedule_trigger_node(graph, **overrides) -> ScheduleTriggerNode:
    fields = {"graph": graph, "node_name": "schedule-1", "is_active": True}
    fields.update(overrides)
    return ScheduleTriggerNode.objects.create(**fields)


@sync_to_async
def _node_content_hash(node_id: int) -> str:
    return ScheduleTriggerNode.objects.get(pk=node_id).content_hash


def _schedule_snapshot_entry(node: ScheduleTriggerNode, content_hash: str) -> dict:
    return {
        "id": node.id,
        "graph": node.graph_id,
        "node_name": node.node_name,
        "is_active": True,
        "metadata": {},
        "content_hash": content_hash,
        "current_runs": 0,
        "next_run_date_time": "2026-01-02T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# 1. Wedge-prevention: two flushes in a row succeed after a scheduler
#    deactivation with a live session.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_scheduler_deactivation_does_not_wedge_next_autosave_flush(
    org_graph, regular_user, base_snapshot, schedule_trigger_service
):
    """Before the fix, the scheduler's direct DB write left the live snapshot
    with a stale content_hash, so the next flush's CAS precondition no longer
    matched the DB row and every future flush of the graph wedged."""
    node = await _create_schedule_trigger_node(org_graph)
    seeded_hash = await _node_content_hash(node.id)

    await graph_state_service.seed(
        org_graph.id,
        base_snapshot(
            save_version=org_graph.save_version,
            schedule_trigger_node_list=[_schedule_snapshot_entry(node, seeded_hash)],
        ),
    )

    communicator = _make_communicator(org_graph.pk, regular_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    service = schedule_trigger_service
    await sync_to_async(service.deactivate_node)(node.id)

    # The consumer's schedule_node_deactivated handler mutates the snapshot
    # before it sends node_updated — receiving this message proves the
    # mutation already happened.
    message = await communicator.receive_json_from()
    assert message["type"] == "node_updated"

    snapshot = await graph_state_service.get_snapshot(org_graph.id)
    entry = snapshot["schedule_trigger_node_list"][0]
    assert entry["is_active"] is False
    assert entry["next_run_date_time"] is None
    assert entry["content_hash"] == await _node_content_hash(node.id)

    flush_service = GraphFlushService()
    outcome = await flush_service.flush(org_graph.id)
    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). This is the exact "
        "scheduler-vs-autosave wedge this fix targets."
    )

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 2. No-session path: DB write always happens; broadcast is a no-op.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deactivation_with_no_live_session_still_persists_and_skips_broadcast(
    test_graph, schedule_trigger_service
):
    node = await _create_schedule_trigger_node(test_graph)
    assert await graph_state_service.get_snapshot(test_graph.id) is None

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(graph_group_name(test_graph.id), channel_name)

    service = schedule_trigger_service
    await sync_to_async(service.deactivate_node)(node.id)

    persisted = await get_node("schedule_trigger_node_list", node.id)
    assert persisted.is_active is False
    assert persisted.next_run_date_time is None

    # No live snapshot existed, so no message was ever sent to the group.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(channel_layer.receive(channel_name), timeout=0.2)


# ---------------------------------------------------------------------------
# 3. Idempotency: safe to invoke twice for the same deactivation event.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_scheduler_deactivation_is_idempotent(test_graph, base_snapshot):
    node = await _create_schedule_trigger_node(test_graph)
    seeded_hash = await _node_content_hash(node.id)

    await graph_state_service.seed(
        test_graph.id,
        base_snapshot(
            save_version=test_graph.save_version,
            schedule_trigger_node_list=[_schedule_snapshot_entry(node, seeded_hash)],
        ),
    )

    # Flip the DB row first (mirrors the real ordering: scheduler always
    # writes the DB before any collab-layer mirroring happens).
    await sync_to_async(
        lambda: ScheduleTriggerNode.objects.filter(pk=node.id).update(is_active=False)
    )()

    first = await graph_state_service.apply_scheduler_deactivation(
        test_graph.id, node.id, "schedule_trigger_node_list"
    )
    assert first is True

    second = await graph_state_service.apply_scheduler_deactivation(
        test_graph.id, node.id, "schedule_trigger_node_list"
    )
    assert second is False

    snapshot = await graph_state_service.get_snapshot(test_graph.id)
    entry = snapshot["schedule_trigger_node_list"][0]
    assert entry["is_active"] is False
    assert entry["next_run_date_time"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_scheduler_deactivation_no_snapshot_returns_false(test_graph):
    assert await graph_state_service.get_snapshot(test_graph.id) is None
    result = await graph_state_service.apply_scheduler_deactivation(
        test_graph.id, 12345, "schedule_trigger_node_list"
    )
    assert result is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_scheduler_deactivation_node_absent_from_snapshot_returns_false(
    test_graph, base_snapshot
):
    await graph_state_service.seed(
        test_graph.id, base_snapshot(save_version=test_graph.save_version)
    )
    result = await graph_state_service.apply_scheduler_deactivation(
        test_graph.id, 999999, "schedule_trigger_node_list"
    )
    assert result is False


# ---------------------------------------------------------------------------
# 4. Broadcast shape: the consumer's outbound message matches NodeUpdatedMessage.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_consumer_broadcasts_display_only_node_updated(
    org_graph, regular_user, base_snapshot
):
    node = await _create_schedule_trigger_node(org_graph)
    seeded_hash = await _node_content_hash(node.id)

    await graph_state_service.seed(
        org_graph.id,
        base_snapshot(
            save_version=org_graph.save_version,
            schedule_trigger_node_list=[_schedule_snapshot_entry(node, seeded_hash)],
        ),
    )

    communicator = _make_communicator(org_graph.pk, regular_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    # Flip the DB row directly (simulates the scheduler's write) and fire the
    # channel-layer event exactly as GraphEditNotifier.notify_schedule_node_
    # deactivated would, without going through ScheduleTriggerService.
    await sync_to_async(
        lambda: ScheduleTriggerNode.objects.filter(pk=node.id).update(is_active=False)
    )()

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        graph_group_name(org_graph.id),
        {
            "type": "schedule_node_deactivated",
            "graph_id": org_graph.id,
            "node_id": node.id,
            "list_key": "schedule_trigger_node_list",
        },
    )

    message = await communicator.receive_json_from()
    assert message["type"] == "node_updated"
    assert message["node"] == {
        "id": node.id,
        "is_active": False,
        "next_run_date_time": None,
    }
    assert message["list_key"] == "schedule_trigger_node_list"
    assert message["changed_fields"] == ["is_active", "next_run_date_time"]
    assert message["editor"]["user_id"] == 0
    assert "content_hash" not in message["node"]
    assert "content_hash" not in message

    snapshot = await graph_state_service.get_snapshot(org_graph.id)
    entry = snapshot["schedule_trigger_node_list"][0]
    assert entry["is_active"] is False
    assert entry["next_run_date_time"] is None

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 5. DRY-both-paths: deactivate_node and _deactivate both notify identically.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deactivate_node_path_broadcasts_schedule_node_deactivated(
    test_graph, base_snapshot, schedule_trigger_service
):
    node = await _create_schedule_trigger_node(test_graph)
    await graph_state_service.seed(
        test_graph.id, base_snapshot(save_version=test_graph.save_version)
    )

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(graph_group_name(test_graph.id), channel_name)

    service = schedule_trigger_service
    await sync_to_async(service.deactivate_node)(node.id)

    message = await asyncio.wait_for(channel_layer.receive(channel_name), timeout=1.0)
    assert message["type"] == "schedule_node_deactivated"
    assert message["graph_id"] == test_graph.id
    assert message["node_id"] == node.id
    assert message["list_key"] == "schedule_trigger_node_list"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_internal_deactivate_path_broadcasts_schedule_node_deactivated(
    test_graph, base_snapshot, schedule_trigger_service
):
    """Exercises the other call site (_deactivate, reached from
    handle_schedule_trigger's end-date terminal condition) to prove both
    paths share the same notification, not just deactivate_node."""
    from datetime import timedelta

    from django.utils import timezone

    # end_type=ON_DATE with an end_date_time already in the past makes
    # get_end_condition_strategy select OnDateEndStrategy, whose
    # is_end_date_passed() is True on the first check — handle_schedule_trigger
    # then calls _deactivate and returns before ever starting a session.
    node = await _create_schedule_trigger_node(
        test_graph,
        end_type=ScheduleTriggerNode.EndType.ON_DATE,
        end_date_time=timezone.now() - timedelta(days=1),
    )
    await graph_state_service.seed(
        test_graph.id, base_snapshot(save_version=test_graph.save_version)
    )

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(graph_group_name(test_graph.id), channel_name)

    service = schedule_trigger_service
    await sync_to_async(service.handle_schedule_trigger)(node.id)

    message = await asyncio.wait_for(channel_layer.receive(channel_name), timeout=1.0)
    assert message["type"] == "schedule_node_deactivated"
    assert message["graph_id"] == test_graph.id
    assert message["node_id"] == node.id
    assert message["list_key"] == "schedule_trigger_node_list"


# ---------------------------------------------------------------------------
# Crew cascade delete — helpers
# ---------------------------------------------------------------------------


@sync_to_async
def _create_crew_node(graph, crew: Crew, node_name: str) -> CrewNode:
    """Attach an additional CrewNode to an already-created Crew — used by the
    multi-graph test, where the same crew is placed on two graphs."""
    return CrewNode.objects.create(graph=graph, node_name=node_name, crew=crew)


@sync_to_async
def _delete_crew(crew):
    crew.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_crew_delete_broadcasts_nodes_deleted_per_graph_and_updates_snapshots(
    test_graph, second_graph, default_org, make_crew_node, base_snapshot
):
    """A crew placed on two graphs triggers one nodes_deleted broadcast per
    graph, scoped to that graph's own channel group, and removes the node
    from both graphs' live snapshots."""
    crew, _ = await make_crew_node(default_org, graph=None)
    node_on_first_graph = await _create_crew_node(test_graph, crew, "Crew-Node #1")
    node_on_second_graph = await _create_crew_node(second_graph, crew, "Crew-Node #2")

    await graph_state_service.seed(
        test_graph.id,
        base_snapshot(
            save_version=test_graph.save_version,
            crew_node_list=[
                {
                    "id": node_on_first_graph.id,
                    "graph": test_graph.id,
                    "node_name": "Crew-Node #1",
                    "crew_id": crew.id,
                }
            ],
        ),
    )
    await graph_state_service.seed(
        second_graph.id,
        base_snapshot(
            save_version=second_graph.save_version,
            crew_node_list=[
                {
                    "id": node_on_second_graph.id,
                    "graph": second_graph.id,
                    "node_name": "Crew-Node #2",
                    "crew_id": crew.id,
                }
            ],
        ),
    )

    channel_layer = get_channel_layer()
    first_channel = await channel_layer.new_channel()
    second_channel = await channel_layer.new_channel()
    await channel_layer.group_add(f"graph_edit_{test_graph.id}", first_channel)
    await channel_layer.group_add(f"graph_edit_{second_graph.id}", second_channel)

    await _delete_crew(crew)

    first_message = await channel_layer.receive(first_channel)
    second_message = await channel_layer.receive(second_channel)

    assert first_message["type"] == "nodes_deleted"
    assert first_message["refs"] == [
        {"list_key": "crew_node_list", "id": node_on_first_graph.id, "temp_id": None}
    ]
    assert second_message["type"] == "nodes_deleted"
    assert second_message["refs"] == [
        {"list_key": "crew_node_list", "id": node_on_second_graph.id, "temp_id": None}
    ]

    first_snapshot = await graph_state_service.get_snapshot(test_graph.id)
    assert first_snapshot["crew_node_list"] == []
    second_snapshot = await graph_state_service.get_snapshot(second_graph.id)
    assert second_snapshot["crew_node_list"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_crew_delete_with_no_live_snapshot_is_a_no_op(
    test_graph, default_org, make_crew_node
):
    """When the graph has no live snapshot in Redis (no active collab
    session), broadcast_nodes_deleted must skip silently — no message, no
    crash."""
    crew, _crew_node = await make_crew_node(default_org, graph=test_graph)

    assert await graph_state_service.get_snapshot(test_graph.id) is None

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(f"graph_edit_{test_graph.id}", channel_name)

    await _delete_crew(crew)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(channel_layer.receive(channel_name), timeout=0.5)
