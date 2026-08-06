"""Regression tests for the scheduler-vs-collab-autosave wedge: scheduler
deactivation must broadcast via the channel layer, not mutate the live
snapshot directly, so it never races autosave's content_hash CAS.

The fix (DB-is-authority, collab-layer-is-follower):
 - ``ScheduleTriggerService._persist_deactivation`` writes the DB
   unconditionally, then — via ``transaction.on_commit`` — calls
   ``GraphEditNotifier.notify_schedule_node_deactivated``.
 - That notifier only broadcasts a ``schedule_node_deactivated`` channel-layer
   event (no snapshot mutation — the scheduler runs in a separate OS process
   from the ASGI workers that own the live snapshot's per-graph asyncio lock).
 - ``GraphEditConsumer.schedule_node_deactivated`` (in the ASGI process, under
   the real lock) mutates the snapshot via
   ``GraphLiveStateService.apply_scheduler_deactivation``, then pushes a
   display-only ``node_updated`` to the connected client.
"""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.flush_service import FlushStatus, GraphFlushService
from tables.graph_collab.groups import graph_group_name
from tables.models.graph_models import ScheduleTriggerNode

from tests.graph_collab.conftest import _drain_connect, _make_communicator


@sync_to_async
def _create_schedule_trigger_node(graph, **overrides) -> ScheduleTriggerNode:
    fields = {"graph": graph, "node_name": "schedule-1", "is_active": True}
    fields.update(overrides)
    return ScheduleTriggerNode.objects.create(**fields)


@sync_to_async
def _get_schedule_trigger_node(node_id: int) -> ScheduleTriggerNode:
    return ScheduleTriggerNode.objects.get(pk=node_id)


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

    persisted = await _get_schedule_trigger_node(node.id)
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
    handle_schedule_trigger's end-date/max-runs terminal conditions) to prove
    both paths share the same notification, not just deactivate_node."""
    node = await _create_schedule_trigger_node(test_graph)
    await graph_state_service.seed(
        test_graph.id, base_snapshot(save_version=test_graph.save_version)
    )

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(graph_group_name(test_graph.id), channel_name)

    service = schedule_trigger_service
    node_instance = await _get_schedule_trigger_node(node.id)
    await sync_to_async(service._deactivate)(node_instance, "test reason")

    message = await asyncio.wait_for(channel_layer.receive(channel_name), timeout=1.0)
    assert message["type"] == "schedule_node_deactivated"
    assert message["graph_id"] == test_graph.id
    assert message["node_id"] == node.id
    assert message["list_key"] == "schedule_trigger_node_list"
