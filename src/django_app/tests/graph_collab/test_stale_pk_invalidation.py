"""Undo/redo stale-pk regression tests: temp_id pruning after flush, the
stale-id-recreate guard on node/connection create, and the deleted_ids
broadcast shape."""

import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.flush_service import FlushStatus, flush_service
from tables.graph_collab.graph_state_service import OpStatus
from tables.graph_collab.notifications import _build_graph_saved_message
from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    EntryDeleteRef,
    NodeCreatedMessage,
    NodesDeletedMessage,
    NodeUpdatedMessage,
)
from tables.models.graph_models import Edge, PythonNode
from tables.models.python_models import PythonCode
from tests.graph_collab.conftest import _editor
from tests.fixtures import *  # noqa: F401,F403


@sync_to_async
def _create_python_setup(graph):
    """Create two PythonNode rows (with their own PythonCode) plus an edge
    between them, in a single sync_to_async hop."""
    python_code_a = PythonCode.objects.create(
        code="def main(): return 0",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    python_code_b = PythonCode.objects.create(
        code="def main(): return 1",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    node_a = PythonNode.objects.create(graph=graph, python_code=python_code_a)
    node_b = PythonNode.objects.create(graph=graph, python_code=python_code_b)
    edge = Edge.objects.create(
        graph=graph, start_node_id=node_a.id, end_node_id=node_b.id
    )
    return node_a, node_b, edge


# ---------------------------------------------------------------------------
# 1. prune_resolved_temp_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_resolved_temp_ids_removes_only_dead_value_entries(
    live_state_service, base_snapshot
):
    """Already-deleted ids get pruned from the redis temp_id->real_id map."""
    await live_state_service.seed(1, base_snapshot())
    await live_state_service.record_resolved_temp_ids(1, {"U": 42, "V": 43, "W": 44})

    await live_state_service.prune_resolved_temp_ids(1, {42, 44})

    resolved = await live_state_service.get_resolved_temp_ids(1)
    assert resolved == {"V": 43}


@pytest.mark.asyncio
async def test_prune_resolved_temp_ids_noop_on_empty_dead_ids(
    live_state_service, base_snapshot
):
    """An empty set of deleted ids must not mutate the map."""
    await live_state_service.seed(1, base_snapshot())
    await live_state_service.record_resolved_temp_ids(1, {"U": 42})

    await live_state_service.prune_resolved_temp_ids(1, set())

    resolved = await live_state_service.get_resolved_temp_ids(1)
    assert resolved == {"U": 42}


@pytest.mark.asyncio
async def test_prune_resolved_temp_ids_preserves_ttl(
    live_state_service, base_snapshot, settings
):
    """Pruning must not reset the map's TTL."""
    settings.GRAPH_LIVE_STATE_TTL_SECONDS = 3600
    await live_state_service.seed(1, base_snapshot())
    await live_state_service.record_resolved_temp_ids(1, {"U": 42, "V": 43})

    await live_state_service.prune_resolved_temp_ids(1, {42})

    ttl = await live_state_service._redis.ttl("graph:live:1:tempids")
    assert 3590 <= ttl <= 3600


@pytest.mark.asyncio
async def test_prune_resolved_temp_ids_alive_temp_id_still_resolves_after_prune(
    live_state_service, base_snapshot
):
    """A temp_id whose real id is still alive keeps resolving after an
    unrelated dead pk is pruned."""
    await live_state_service.seed(
        1,
        base_snapshot(python_node_list=[{"id": 100, "node_name": "alive"}]),
    )
    await live_state_service.record_resolved_temp_ids(1, {"DEAD": 999, "ALIVE": 100})

    await live_state_service.prune_resolved_temp_ids(1, {999})

    resolved = await live_state_service.get_resolved_temp_ids(1)
    assert resolved == {"ALIVE": 100}

    msg = NodeUpdatedMessage(
        node={"temp_id": "ALIVE", "node_name": "renamed"},
        list_key="python_node_list",
        editor=_editor(),
        changed_fields=["node_name"],
    )
    result = await live_state_service.apply_op(1, msg)
    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["python_node_list"][0]["node_name"] == "renamed"


@pytest.mark.asyncio
async def test_legacy_node_updated_by_temp_id_resolves_via_resolved_map(
    live_state_service, base_snapshot
):
    """A legacy NodeUpdatedMessage (changed_fields=None) carrying only a
    resolved-and-stripped temp_id must update the real entry in place, not
    append a duplicate/orphan entry."""
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 100, "node_name": "alive"}])
    )
    await live_state_service.record_resolved_temp_ids(1, {"ALIVE": 100})

    msg = NodeUpdatedMessage(
        node={"temp_id": "ALIVE", "node_name": "renamed"},
        list_key="python_node_list",
        editor=_editor(),
        changed_fields=None,
    )
    result = await live_state_service.apply_op(1, msg)
    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert len(snapshot["python_node_list"]) == 1
    assert snapshot["python_node_list"][0]["id"] == 100
    assert snapshot["python_node_list"][0]["node_name"] == "renamed"


@pytest.mark.asyncio
async def test_node_created_by_temp_id_resolving_to_alive_id_is_rejected(
    live_state_service, base_snapshot
):
    """A stale replayed create referencing an already-resolved temp_id gets
    rewritten to the live row's real id and rejected, since that id is alive
    (not pending delete)."""
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 100, "node_name": "alive"}])
    )
    await live_state_service.record_resolved_temp_ids(1, {"ALIVE": 100})

    msg = NodeCreatedMessage(
        node={"temp_id": "ALIVE", "node_name": "duplicate-attempt"},
        list_key="python_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["python_node_list"] == [{"id": 100, "node_name": "alive"}]


@pytest.mark.asyncio
async def test_node_created_by_temp_id_resolving_to_pending_delete_id_is_resurrected(
    live_state_service, base_snapshot
):
    """Resurrect via temp_id: create -> delete queued (pre-flush) -> undo
    re-sends the create by the original temp_id, which resolves to the still
    pending-delete real id and is accepted, restoring the entry."""
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 100, "node_name": "n"}])
    )
    await live_state_service.record_resolved_temp_ids(1, {"ORIGINAL": 100})

    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="python_node_list", id=100)],
        editor=_editor(),
    )
    delete_result = await live_state_service.apply_op(1, delete_msg)
    assert delete_result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["python_node_list"] == []
    assert snapshot["deleted"]["python_node_ids"] == [100]

    recreate_msg = NodeCreatedMessage(
        node={"temp_id": "ORIGINAL", "node_name": "n"},
        list_key="python_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, recreate_msg)

    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["python_node_list"] == [{"id": 100, "node_name": "n"}]
    assert snapshot["deleted"]["python_node_ids"] == []


# ---------------------------------------------------------------------------
# 4. apply_id_remap prunes based on flushed_deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_prunes_based_on_flushed_deleted(
    live_state_service, base_snapshot
):
    await live_state_service.seed(1, base_snapshot())
    await live_state_service.record_resolved_temp_ids(1, {"OLD": 99, "KEEP": 100})

    await live_state_service.apply_id_remap(
        1,
        temp_id_map={},
        new_save_version=2,
        flushed_deleted={"python_node_ids": [99]},
    )

    resolved = await live_state_service.get_resolved_temp_ids(1)
    assert resolved == {"KEEP": 100}


# ---------------------------------------------------------------------------
# 5. graph_saved carries deleted_ids, including cascade-deleted edges
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_and_graph_saved_message_carry_cascade_deleted_edge_ids(
    graph, live_state_service
):
    node_a, _node_b, edge = await _create_python_setup(graph)

    seeded = await live_state_service.seed_from_db(graph.id)
    assert seeded

    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="python_node_list", id=node_a.id)],
        editor=_editor(),
    )
    delete_result = await live_state_service.apply_op(graph.id, delete_msg)
    assert delete_result.status is OpStatus.APPLIED

    outcome = await flush_service.flush(graph.id)
    assert outcome.status is FlushStatus.SAVED, outcome.failure_reason

    flushed_deleted = outcome.result.flushed_deleted
    assert flushed_deleted.get("python_node_ids") == [node_a.id]
    assert flushed_deleted.get("edge_ids") == [edge.id]

    message = _build_graph_saved_message(
        graph_id=graph.id,
        new_save_version=outcome.result.new_save_version,
        user=None,
        saved_at=outcome.result.saved_at,
        deleted_ids=flushed_deleted,
    )
    assert message["deleted_ids"]["python_node_ids"] == [node_a.id]
    assert message["deleted_ids"]["edge_ids"] == [edge.id]


# ---------------------------------------------------------------------------
# 6 / 7. node_created with real id is rejected; legacy node_updated is not
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_created_with_real_id_is_rejected(live_state_service, base_snapshot):
    """A bare real id never seen before, and a real id whose deletion was
    already flushed (no longer pending), are both rejected as stale replays."""
    await live_state_service.seed(1, base_snapshot())
    msg = NodeCreatedMessage(
        node={"id": 42, "node_name": "stale-undo-recreate"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["crew_node_list"] == []

    await live_state_service.seed(
        2, base_snapshot(crew_node_list=[{"id": 25, "node_name": "n"}])
    )
    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=25)],
        editor=_editor(),
    )
    await live_state_service.apply_op(2, delete_msg)
    await live_state_service.apply_id_remap(
        2,
        temp_id_map={},
        new_save_version=2,
        flushed_deleted={"crew_node_ids": [25]},
    )
    snapshot = await live_state_service.get_snapshot(2)
    assert snapshot["deleted"]["crew_node_ids"] == []

    recreate_msg = NodeCreatedMessage(
        node={"id": 25, "node_name": "n"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(2, recreate_msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(2)
    assert snapshot["crew_node_list"] == []


@pytest.mark.asyncio
async def test_legacy_node_updated_with_real_id_is_still_accepted(
    live_state_service, base_snapshot
):
    """A legacy NodeUpdatedMessage (changed_fields=None) carrying a real id —
    the shape decision-table routing sync sends — must not be caught by the
    node_created stale-id-recreate guard."""
    await live_state_service.seed(1, base_snapshot())
    msg = NodeUpdatedMessage(
        node={"id": 42, "node_name": "decision-routing-update"},
        list_key="crew_node_list",
        editor=_editor(),
        changed_fields=None,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["crew_node_list"] == [
        {"id": 42, "node_name": "decision-routing-update"}
    ]


# ---------------------------------------------------------------------------
# Bonus: connection_created with real id is rejected — the exact shape that
# produced the "id=4 not found in graph 2" bulk-save log.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_created_with_real_id_is_rejected(
    live_state_service, base_snapshot
):
    await live_state_service.seed(1, base_snapshot())
    msg = ConnectionCreatedMessage(
        connection={"id": 4, "start_node_id": 1, "end_node_id": 2},
        list_key="edge_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == []


# ---------------------------------------------------------------------------
# 8. Pre-flush undo/resurrect window: id pending in the `deleted` accumulator
#    must be ACCEPTED, not rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_created_with_id_pending_delete_is_accepted_and_unqueued(
    live_state_service, base_snapshot
):
    """Create -> delete (pre-flush, id queued in the accumulator) -> undo
    re-sends node_created with the real id. Must be APPLIED, the entry
    restored, and the id removed from the accumulator."""
    await live_state_service.seed(
        1, base_snapshot(crew_node_list=[{"id": 25, "node_name": "n"}])
    )
    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=25)],
        editor=_editor(),
    )
    delete_result = await live_state_service.apply_op(1, delete_msg)
    assert delete_result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["crew_node_list"] == []
    assert snapshot["deleted"]["crew_node_ids"] == [25]

    recreate_msg = NodeCreatedMessage(
        node={"id": 25, "node_name": "n"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, recreate_msg)

    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["crew_node_list"] == [{"id": 25, "node_name": "n"}]
    assert snapshot["deleted"]["crew_node_ids"] == []


@pytest.mark.asyncio
async def test_node_created_with_id_not_pending_delete_is_rejected(
    live_state_service, base_snapshot
):
    """Same real id as the resurrect case, but the deletion has already been
    flushed — a subsequent create carrying that dead pk is a stale replay."""
    await live_state_service.seed(
        1, base_snapshot(crew_node_list=[{"id": 25, "node_name": "n"}])
    )
    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=25)],
        editor=_editor(),
    )
    await live_state_service.apply_op(1, delete_msg)

    await live_state_service.apply_id_remap(
        1,
        temp_id_map={},
        new_save_version=2,
        flushed_deleted={"crew_node_ids": [25]},
    )
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["deleted"]["crew_node_ids"] == []

    recreate_msg = NodeCreatedMessage(
        node={"id": 25, "node_name": "n"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, recreate_msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["crew_node_list"] == []


@pytest.mark.asyncio
async def test_connection_created_with_id_pending_delete_is_accepted_and_unqueued(
    live_state_service, base_snapshot
):
    """Same pre-flush resurrect window as nodes, for connection_created /
    edge_ids."""
    await live_state_service.seed(
        1, base_snapshot(edge_list=[{"id": 4, "start_node_id": 1, "end_node_id": 2}])
    )
    delete_msg = ConnectionDeletedMessage(
        connection_id=4,
        list_key="edge_list",
        editor=_editor(),
    )
    delete_result = await live_state_service.apply_op(1, delete_msg)
    assert delete_result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == []
    assert snapshot["deleted"]["edge_ids"] == [4]

    recreate_msg = ConnectionCreatedMessage(
        connection={"id": 4, "start_node_id": 1, "end_node_id": 2},
        list_key="edge_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, recreate_msg)

    assert result.status is OpStatus.APPLIED

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 4, "start_node_id": 1, "end_node_id": 2}]
    assert snapshot["deleted"]["edge_ids"] == []


@pytest.mark.asyncio
async def test_connection_created_with_id_not_pending_delete_is_rejected(
    live_state_service, base_snapshot
):
    """Same real id as the resurrect case, but the deletion has already been
    flushed — the create must be rejected as a stale replay."""
    await live_state_service.seed(
        1, base_snapshot(edge_list=[{"id": 4, "start_node_id": 1, "end_node_id": 2}])
    )
    delete_msg = ConnectionDeletedMessage(
        connection_id=4,
        list_key="edge_list",
        editor=_editor(),
    )
    await live_state_service.apply_op(1, delete_msg)

    await live_state_service.apply_id_remap(
        1,
        temp_id_map={},
        new_save_version=2,
        flushed_deleted={"edge_ids": [4]},
    )
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["deleted"]["edge_ids"] == []

    recreate_msg = ConnectionCreatedMessage(
        connection={"id": 4, "start_node_id": 1, "end_node_id": 2},
        list_key="edge_list",
        editor=_editor(),
    )
    result = await live_state_service.apply_op(1, recreate_msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "stale_id_recreate"
    assert result.relay is False

    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == []


# ---------------------------------------------------------------------------
# 9. _build_graph_saved_message drops empty delete-key lists
# ---------------------------------------------------------------------------


def test_build_graph_saved_message_drops_empty_deleted_lists():
    """Only delete_ids keys with real ids survive; an unfiltered pass-through
    would broadcast every empty-list key on every autosave tick. Absent
    deleted_ids yields an empty dict too."""
    message = _build_graph_saved_message(
        graph_id=1,
        new_save_version=2,
        user=None,
        saved_at="2026-01-01T00:00:00+00:00",
        deleted_ids={
            "crew_node_ids": [],
            "python_node_ids": [7],
            "edge_ids": [],
            "conditional_edge_ids": [9, 10],
        },
    )
    assert message["deleted_ids"] == {
        "python_node_ids": [7],
        "conditional_edge_ids": [9, 10],
    }

    message_no_deleted_ids = _build_graph_saved_message(
        graph_id=1,
        new_save_version=2,
        user=None,
        saved_at="2026-01-01T00:00:00+00:00",
    )
    assert message_no_deleted_ids["deleted_ids"] == {}
