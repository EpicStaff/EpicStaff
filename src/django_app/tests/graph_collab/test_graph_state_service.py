"""
Unit tests for GraphLiveStateService.

Redis is replaced with fakeredis.aioredis.FakeRedis so the real async
get/set/delete logic runs without a live server.
"""

import pytest

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    ConnectionWaypointsUpdatedMessage,
    ConnectionsDeletedMessage,
    EntryDeleteRef,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
)
from tests.graph_collab.conftest import PYTHON_CODE_DATA

# This file's apply_id_remap calls use fake ids (e.g. 42) that do not
# correspond to real DB rows, and most tests here are not django_db-marked,
# so the content_hash DB refresh step is patched out for every test in the
# file (dedicated DB-backed coverage for the refresh itself lives in
# test_content_hash_refresh.py).
pytestmark = pytest.mark.usefixtures("noop_content_hash_refresh")


# ---------------------------------------------------------------------------
# seed / get_snapshot / clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_and_get_round_trip(live_state_service, base_snapshot):
    flow = base_snapshot(
        crew_node_list=[{"id": 1, "crew_id": 7, "node_name": "Crew #1"}]
    )
    await live_state_service.seed(1, flow)
    result = await live_state_service.get_snapshot(1)
    assert result == flow


@pytest.mark.asyncio
async def test_get_snapshot_absent_returns_none(live_state_service):
    result = await live_state_service.get_snapshot(999)
    assert result is None


@pytest.mark.asyncio
async def test_clear_removes_snapshot(live_state_service, base_snapshot):
    await live_state_service.seed(2, base_snapshot())
    await live_state_service.clear(2)
    assert await live_state_service.get_snapshot(2) is None


# ---------------------------------------------------------------------------
# apply_op — node ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_node_created_adds_node(live_state_service, base_snapshot, editor):
    await live_state_service.seed(1, base_snapshot())
    msg = NodeCreatedMessage(
        node={"temp_id": "n1", "node_name": "Crew #1", "crew_id": 7},
        list_key="crew_node_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)

    assert snapshot["crew_node_list"] == [
        {"temp_id": "n1", "node_name": "Crew #1", "crew_id": 7}
    ]


@pytest.mark.asyncio
async def test_apply_node_updated_replaces_node(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1,
        base_snapshot(crew_node_list=[{"id": 1, "crew_id": 7, "node_name": "old"}]),
    )
    msg = NodeUpdatedMessage(
        node={"id": 1, "crew_id": 7, "node_name": "new"},
        list_key="crew_node_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert len(snapshot["crew_node_list"]) == 1
    assert snapshot["crew_node_list"][0]["node_name"] == "new"


@pytest.mark.asyncio
async def test_apply_node_updated_upserts_when_absent(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(1, base_snapshot())
    msg = NodeUpdatedMessage(
        node={"id": 99, "node_name": "Python #1", "python_code": PYTHON_CODE_DATA},
        list_key="python_node_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert len(snapshot["python_node_list"]) == 1
    assert snapshot["python_node_list"][0]["id"] == 99


@pytest.mark.asyncio
async def test_apply_nodes_deleted_removes_nodes(
    live_state_service, base_snapshot, editor
):
    # _match_entry matches integer ids against integer ids. Use integer node ids.
    initial_nodes = [
        {"id": 10, "crew_id": 1, "node_name": "Crew #1"},
        {"id": 20, "crew_id": 2, "node_name": "Crew #2"},
        {"id": 30, "crew_id": 3, "node_name": "Crew #3"},
    ]
    await live_state_service.seed(1, base_snapshot(crew_node_list=initial_nodes))
    msg = NodesDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="crew_node_list", id=10),
            EntryDeleteRef(list_key="crew_node_list", id=30),
        ],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    # The full surviving entry is compared, proving it was left byte-identical.
    assert snapshot["crew_node_list"] == [
        {"id": 20, "crew_id": 2, "node_name": "Crew #2"}
    ]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_does_not_touch_connections(
    live_state_service, base_snapshot, editor
):
    # Endpoints deliberately reference nodes OTHER than the one being deleted
    # (100) — see test_apply_nodes_deleted_cascades_edges_referencing_deleted_node
    # for the case where an edge DOES reference the deleted node and IS
    # cascaded. This test proves the opposite: an edge unrelated to the
    # deleted node survives untouched.
    edges = [{"id": 1, "start_node_id": 998, "end_node_id": 999}]
    await live_state_service.seed(
        1, base_snapshot(crew_node_list=[{"id": 100}], edge_list=edges)
    )
    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=100)],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    # Connections not referencing the deleted node are untouched.
    assert snapshot["edge_list"] == edges


# ---------------------------------------------------------------------------
# apply_op — NodesDeletedMessage cascades to referencing edges/routing refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_nodes_deleted_cascades_edges_referencing_deleted_node(
    live_state_service, base_snapshot, editor
):
    """Deleting a node also drops its edge_list / conditional_edge_list entries
    (real refs — start_node_id/end_node_id/source_node_id) and queues their
    real ids for deletion, so the next flush removes the orphan rows too.
    """
    flow = base_snapshot(crew_node_list=[{"id": 100}, {"id": 200}])
    flow["edge_list"] = [
        {"id": 47, "start_node_id": 100, "end_node_id": 200},
        {"id": 48, "start_node_id": 200, "end_node_id": 999},
        {"id": 49, "start_node_id": 300, "end_node_id": 400},
    ]
    flow["conditional_edge_list"] = [
        {"id": 7, "source_node_id": 200},
        {"id": 8, "source_node_id": 300},
    ]
    await live_state_service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)

    # Edges referencing the deleted node (either endpoint) are dropped.
    assert snapshot["edge_list"] == [
        {"id": 49, "start_node_id": 300, "end_node_id": 400}
    ]
    assert snapshot["conditional_edge_list"] == [{"id": 8, "source_node_id": 300}]

    # Their real ids are queued for DB deletion.
    assert sorted(snapshot["deleted"]["edge_ids"]) == [47, 48]
    assert snapshot["deleted"]["conditional_edge_ids"] == [7]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_dedupes_edge_id_already_accumulated(
    live_state_service, base_snapshot, editor
):
    """An edge already queued for deletion by a prior connections_deleted op
    must not be duplicated when a subsequent node delete also cascades to it.
    """
    flow = base_snapshot(
        crew_node_list=[{"id": 100}, {"id": 200}],
        edge_list=[{"id": 47, "start_node_id": 100, "end_node_id": 200}],
        deleted={"edge_ids": [47], "conditional_edge_ids": []},
    )
    await live_state_service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)

    assert snapshot["edge_list"] == []
    assert snapshot["deleted"]["edge_ids"] == [47]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_nulls_decision_table_routing_refs(
    live_state_service, base_snapshot, editor
):
    """Deleting a node clears any decision-table routing ref pointing at it —
    default_next_node_id, next_error_node_id, and per-group next_node_id —
    on both DecisionTableNode and ClassificationDecisionTableNode entries.
    """
    flow = base_snapshot(
        crew_node_list=[{"id": 200}],
        decision_table_node_list=[
            {
                "id": 1,
                "default_next_node_id": 200,
                "next_error_node_id": 300,
                "condition_groups": [
                    {"id": 10, "next_node_id": 200},
                    {"id": 11, "next_node_id": 400},
                ],
            }
        ],
        classification_decision_table_node_list=[
            {"id": 2, "default_next_node_id": 300, "next_error_node_id": 200}
        ],
    )
    await live_state_service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)

    decision_table = snapshot["decision_table_node_list"][0]
    assert decision_table["default_next_node_id"] is None
    assert decision_table["next_error_node_id"] == 300
    assert decision_table["condition_groups"][0]["next_node_id"] is None
    assert decision_table["condition_groups"][1]["next_node_id"] == 400

    classification_table = snapshot["classification_decision_table_node_list"][0]
    assert classification_table["default_next_node_id"] == 300
    assert classification_table["next_error_node_id"] is None


@pytest.mark.asyncio
async def test_apply_nodes_deleted_temp_only_ref_skips_cascade(
    live_state_service, base_snapshot, editor
):
    """A temp_id-only delete ref (never persisted) must not attempt cascade —
    it can only match string temp_ids, never a real edge/routing int ref.
    """
    flow = base_snapshot(
        crew_node_list=[{"temp_id": "new-node"}],
        edge_list=[{"id": 1, "start_node_id": 999, "end_node_id": 998}],
    )
    await live_state_service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", temp_id="new-node")],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)

    assert snapshot["crew_node_list"] == []
    assert snapshot["edge_list"] == [
        {"id": 1, "start_node_id": 999, "end_node_id": 998}
    ]
    assert snapshot["deleted"]["edge_ids"] == []


# ---------------------------------------------------------------------------
# apply_op — connection ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_connection_created_adds_connection(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(1, base_snapshot())
    msg = ConnectionCreatedMessage(
        connection={"temp_id": "c1", "start_node_id": 1, "end_node_id": 2},
        list_key="edge_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == [
        {"temp_id": "c1", "start_node_id": 1, "end_node_id": 2}
    ]


@pytest.mark.asyncio
async def test_apply_connection_created_upserts_existing(
    live_state_service, base_snapshot, editor
):
    existing = [{"temp_id": "c1", "start_node_id": 1, "end_node_id": 2}]
    await live_state_service.seed(1, base_snapshot(edge_list=existing))
    msg = ConnectionCreatedMessage(
        connection={"temp_id": "c1", "start_node_id": 1, "end_node_id": 3},
        list_key="edge_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert len(snapshot["edge_list"]) == 1
    assert snapshot["edge_list"][0]["end_node_id"] == 3


@pytest.mark.asyncio
async def test_apply_connection_deleted_removes_connection(
    live_state_service, base_snapshot, editor
):
    connections = [
        {"id": 1, "start_node_id": 10, "end_node_id": 20},
        {"id": 2, "start_node_id": 30, "end_node_id": 40},
    ]
    await live_state_service.seed(1, base_snapshot(edge_list=connections))
    msg = ConnectionDeletedMessage(
        connection_id=1,
        list_key="edge_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2, "start_node_id": 30, "end_node_id": 40}]


@pytest.mark.asyncio
async def test_apply_connections_deleted_removes_batch(
    live_state_service, base_snapshot, editor
):
    connections = [
        {"id": 1, "start_node_id": 10, "end_node_id": 20},
        {"id": 2, "start_node_id": 30, "end_node_id": 40},
        {"id": 3, "start_node_id": 50, "end_node_id": 60},
    ]
    await live_state_service.seed(1, base_snapshot(edge_list=connections))
    msg = ConnectionsDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="edge_list", id=1),
            EntryDeleteRef(list_key="edge_list", id=3),
        ],
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2, "start_node_id": 30, "end_node_id": 40}]


@pytest.mark.asyncio
async def test_apply_connection_waypoints_updated_sets_waypoints(
    live_state_service, base_snapshot, editor
):
    connections = [{"id": 1, "start_node_id": 10, "end_node_id": 20}]
    await live_state_service.seed(1, base_snapshot(edge_list=connections))
    waypoints = [{"x": 10, "y": 20}, {"x": 30, "y": 40}]
    msg = ConnectionWaypointsUpdatedMessage(
        connection_id=1,
        waypoints=waypoints,
        list_key="edge_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, msg)
    snapshot = await live_state_service.get_snapshot(1)
    assert snapshot["edge_list"][0]["waypoints"] == waypoints


# ---------------------------------------------------------------------------
# apply_op — safe no-op on absent snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_op_on_absent_snapshot_is_safe_noop(live_state_service, editor):
    msg = NodeCreatedMessage(
        node={"temp_id": "n1"}, list_key="crew_node_list", editor=editor
    )
    # Must not raise and must not create a snapshot.
    await live_state_service.apply_op(999, msg)
    assert await live_state_service.get_snapshot(999) is None


# ---------------------------------------------------------------------------
# seed_from_db — TOCTOU race guard
# ---------------------------------------------------------------------------


def _async_return(value):
    async def _coro(*_args, **_kwargs):
        return value

    return _coro


@pytest.mark.asyncio
async def test_seed_from_db_not_found_returns_false(live_state_service, monkeypatch):
    monkeypatch.setattr(_gss_module, "_load_graph_snapshot", _async_return(None))
    result = await live_state_service.seed_from_db(42)
    assert result is False
    assert await live_state_service.get_snapshot(42) is None


@pytest.mark.asyncio
async def test_seed_from_db_seeds_when_absent(
    live_state_service, base_snapshot, monkeypatch
):
    db_snapshot = base_snapshot(
        crew_node_list=[{"id": 1, "crew_id": 7, "node_name": "Crew #1"}]
    )
    monkeypatch.setattr(_gss_module, "_load_graph_snapshot", _async_return(db_snapshot))
    result = await live_state_service.seed_from_db(7)
    assert result is True
    assert await live_state_service.get_snapshot(7) == db_snapshot
    assert live_state_service.current_revision(7) == 0


@pytest.mark.asyncio
async def test_seed_from_db_does_not_stomp_concurrently_seeded_snapshot(
    live_state_service, base_snapshot, monkeypatch
):
    """The seed_from_db TOCTOU race guard.

    Simulates a late racer: a concurrent connection already seeded the graph
    and a client already applied an op on top of it (marker node present).
    The late racer's DB load (patched here) returns a barer snapshot that
    must NOT overwrite the already-seeded live state.
    """
    graph_id = 5

    # Arrange: live snapshot already seeded + a client op applied on top,
    # carrying a distinctive marker node that a stale DB read would not have.
    already_seeded_snapshot = base_snapshot(
        crew_node_list=[
            {"id": 1, "crew_id": 7, "node_name": "Crew #1"},
            {"temp_id": "marker-node", "crew_id": 99, "node_name": "Marker Node"},
        ]
    )
    await live_state_service.seed(graph_id, already_seeded_snapshot)
    live_state_service._revision[graph_id] = 3
    live_state_service._flushed_revision[graph_id] = 0

    # The late racer's stale DB read — barer, missing the marker node.
    stale_db_snapshot = base_snapshot(
        crew_node_list=[{"id": 1, "crew_id": 7, "node_name": "Crew #1"}]
    )
    monkeypatch.setattr(
        _gss_module, "_load_graph_snapshot", _async_return(stale_db_snapshot)
    )

    # Act
    result = await live_state_service.seed_from_db(graph_id)

    # Assert: seed_from_db reports success but must not stomp the live state.
    assert result is True
    snapshot = await live_state_service.get_snapshot(graph_id)
    assert snapshot == already_seeded_snapshot
    assert any(
        entry.get("temp_id") == "marker-node" for entry in snapshot["crew_node_list"]
    )
    # Revision counters must be untouched — a stomp would reset both to 0.
    assert live_state_service.current_revision(graph_id) == 3
    assert live_state_service._flushed_revision[graph_id] == 0


# ---------------------------------------------------------------------------
# apply_op — singleton dedup for start_node_list / end_node_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", ["start_node_list", "end_node_list"])
async def test_apply_op_singleton_created_with_mismatched_temp_id_never_appends(
    live_state_service, base_snapshot, editor, list_key
):
    """Two NodeCreated ops for a singleton list, each carrying a different
    temp_id, must never leave more than one entry in the snapshot — the
    second op replaces the first instead of appending a duplicate.
    """
    graph_id = 1
    await live_state_service.seed(graph_id, base_snapshot())

    first_msg = NodeCreatedMessage(
        node={"temp_id": "temp-a"},
        list_key=list_key,
        editor=editor,
    )
    await live_state_service.apply_op(graph_id, first_msg)

    second_msg = NodeCreatedMessage(
        node={"temp_id": "temp-b"},
        list_key=list_key,
        editor=editor,
    )
    await live_state_service.apply_op(graph_id, second_msg)

    snapshot = await live_state_service.get_snapshot(graph_id)
    assert len(snapshot[list_key]) == 1
    assert snapshot[list_key][0].get("temp_id") == "temp-b"


_SINGLETON_EXTRA_FIELD = {
    "start_node_list": ("variables", {"greeting": "hello"}),
    "end_node_list": ("output_map", {"context": "variables"}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", ["start_node_list", "end_node_list"])
async def test_apply_op_singleton_update_without_id_keeps_existing_real_id(
    live_state_service, base_snapshot, editor, list_key
):
    """When the existing singleton entry carries a real (persisted) id and a
    later Created/Updated op arrives with no id (only a temp_id — e.g. a
    reconnect that regenerated the synthetic node client-side), the real id
    must be preserved on the surviving entry so the next flush treats it as
    an UPDATE, never a duplicate create.

    _collapse_singleton_entry grafts the existing id onto the new entry and
    then replaces the list wholesale (``entries[:] = [new_entry]``), so any
    field the incoming message did not carry — here the existing entry's
    ``variables``/``output_map`` — is discarded, not merged.
    """
    graph_id = 1
    extra_field_name, extra_field_value = _SINGLETON_EXTRA_FIELD[list_key]
    flow = base_snapshot(**{list_key: [{"id": 5, extra_field_name: extra_field_value}]})
    await live_state_service.seed(graph_id, flow)

    msg = NodeCreatedMessage(
        node={"temp_id": "temp-c"},
        list_key=list_key,
        editor=editor,
    )
    await live_state_service.apply_op(graph_id, msg)

    snapshot = await live_state_service.get_snapshot(graph_id)
    assert len(snapshot[list_key]) == 1
    survivor = snapshot[list_key][0]
    assert survivor["id"] == 5
    assert "temp_id" not in survivor
    # The wholesale replace discards fields the create did not carry.
    assert extra_field_name not in survivor
    assert await live_state_service.get_resolved_temp_ids(graph_id) == {}


# ---------------------------------------------------------------------------
# dirty tracking (revision counters)
# ---------------------------------------------------------------------------


def _node_created_msg():
    from tables.graph_collab.protocol import NodeCreatedMessage

    return NodeCreatedMessage(
        node={
            "temp_id": "abc-123",
            "graph": 1,
            "python_code": PYTHON_CODE_DATA,
        },
        list_key="python_node_list",
        editor={"user_id": 1, "display_name": "Test", "avatar_url": None},
    )


@pytest.mark.asyncio
async def test_revision_bumps_on_apply_op(live_state_service, base_snapshot):
    graph_id = 1
    await live_state_service.seed(graph_id, base_snapshot())
    live_state_service._revision[graph_id] = 0
    live_state_service._flushed_revision[graph_id] = 0

    assert live_state_service.current_revision(graph_id) == 0
    assert not live_state_service.is_dirty(graph_id)

    await live_state_service.apply_op(graph_id, _node_created_msg())

    assert live_state_service.current_revision(graph_id) == 1
    assert live_state_service.is_dirty(graph_id)


@pytest.mark.asyncio
async def test_mark_flushed_with_captured_revision_leaves_dirty_when_edits_race_flush(
    live_state_service, base_snapshot
):
    """mark_flushed with a captured revision leaves is_dirty True when edits arrived during flush."""
    graph_id = 3
    await live_state_service.seed(graph_id, base_snapshot())
    live_state_service._revision[graph_id] = 0
    live_state_service._flushed_revision[graph_id] = 0

    await live_state_service.apply_op(graph_id, _node_created_msg())
    assert live_state_service.current_revision(graph_id) == 1

    captured = live_state_service.current_revision(graph_id)

    # Simulate an edit arriving during the DB flush.
    await live_state_service.apply_op(graph_id, _node_created_msg())
    assert live_state_service.current_revision(graph_id) == 2

    # Flush completes — mark with the captured (not current) revision.
    live_state_service.mark_flushed(graph_id, captured)

    # Still dirty because revision 2 > flushed 1.
    assert live_state_service.is_dirty(graph_id)


@pytest.mark.asyncio
async def test_clear_resets_revision_state(live_state_service, base_snapshot):
    graph_id = 4
    await live_state_service.seed(graph_id, base_snapshot())
    live_state_service._revision[graph_id] = 0
    live_state_service._flushed_revision[graph_id] = 0

    await live_state_service.apply_op(graph_id, _node_created_msg())
    assert live_state_service.is_dirty(graph_id)

    await live_state_service.clear(graph_id)

    # Both revision and flushed_revision keys are removed; defaults are both 0 → not dirty.
    assert not live_state_service.is_dirty(graph_id)
    assert graph_id not in live_state_service._revision
    assert graph_id not in live_state_service._flushed_revision
