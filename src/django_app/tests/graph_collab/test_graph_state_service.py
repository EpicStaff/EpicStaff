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
    EditorInfo,
    EntryDeleteRef,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Override conftest service fixture: return GraphLiveStateService for these tests."""
    return _gss_module.GraphLiveStateService()


@pytest.fixture(autouse=True)
def noop_content_hash_refresh(monkeypatch):
    """This file's apply_id_remap calls use fake ids (e.g. 42) that do not
    correspond to real DB rows, and most tests here are not django_db-marked.
    Patch out the content_hash DB refresh step (EST-3020, see
    _refresh_flushed_content_hashes) so this file stays DB-free, matching its
    original scope. Dedicated DB-backed coverage for the refresh itself lives
    in test_content_hash_refresh.py.
    """

    async def _noop(snapshot):
        return None

    monkeypatch.setattr(_gss_module, "_refresh_flushed_content_hashes", _noop)


def _editor() -> EditorInfo:
    return EditorInfo(user_id=1, display_name="Test", avatar_url=None)


def _flow(crew_node_list=None, edge_list=None) -> dict:
    """Return a minimal superset-snapshot dict.

    The service stores snapshots in superset/Django serializer form, keyed by
    <type>_node_list / edge_list / conditional_edge_list. Tests must use these
    same keys so apply_op can locate and mutate the right lists.
    """
    return {
        "crew_node_list": crew_node_list or [],
        "edge_list": edge_list or [],
        "conditional_edge_list": [],
    }


# ---------------------------------------------------------------------------
# seed / get_snapshot / clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_and_get_round_trip(service):
    flow = _flow(crew_node_list=[{"id": "n1", "type": "agent"}])
    await service.seed(1, flow)
    result = await service.get_snapshot(1)
    assert result == flow


@pytest.mark.asyncio
async def test_get_snapshot_absent_returns_none(service):
    result = await service.get_snapshot(999)
    assert result is None


@pytest.mark.asyncio
async def test_clear_removes_snapshot(service):
    await service.seed(2, _flow())
    await service.clear(2)
    assert await service.get_snapshot(2) is None


# ---------------------------------------------------------------------------
# apply_op — node ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_node_created_adds_node(service):
    await service.seed(1, _flow())
    msg = NodeCreatedMessage(
        node={"id": "n1", "type": "agent"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)

    # op_normalize.normalize_op_entry is a passthrough copy (the FE already
    # sends bulk-save-shaped payloads) — the stored entry is unchanged.
    assert snapshot["crew_node_list"] == [{"id": "n1", "type": "agent"}]


@pytest.mark.asyncio
async def test_apply_node_updated_replaces_node(service):
    await service.seed(
        1, _flow(crew_node_list=[{"id": "n1", "type": "agent", "label": "old"}])
    )
    msg = NodeUpdatedMessage(
        node={"id": "n1", "type": "agent", "label": "new"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["crew_node_list"]) == 1
    assert snapshot["crew_node_list"][0]["label"] == "new"


@pytest.mark.asyncio
async def test_apply_node_updated_upserts_when_absent(service):
    await service.seed(1, _flow())
    msg = NodeUpdatedMessage(
        node={"id": "n99", "type": "code"},
        list_key="python_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["python_node_list"]) == 1
    assert snapshot["python_node_list"][0]["id"] == "n99"


@pytest.mark.asyncio
async def test_apply_nodes_deleted_removes_nodes(service):
    # _match_entry matches integer ids against integer ids. Use integer node ids.
    initial_nodes = [{"id": 10}, {"id": 20}, {"id": 30}]
    await service.seed(1, _flow(crew_node_list=initial_nodes))
    msg = NodesDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="crew_node_list", id=10),
            EntryDeleteRef(list_key="crew_node_list", id=30),
        ],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["crew_node_list"] == [{"id": 20}]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_does_not_touch_connections(service):
    edges = [{"id": 1, "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(crew_node_list=[{"id": 100}], edge_list=edges))
    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=100)],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    # Connections must be untouched — FE sends connection deletions separately.
    assert snapshot["edge_list"] == edges


# ---------------------------------------------------------------------------
# apply_op — NodesDeletedMessage cascade (EST-3020 Bug 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_nodes_deleted_cascades_edges_referencing_deleted_node(service):
    """Deleting a node also drops its edge_list / conditional_edge_list entries
    (real refs — start_node_id/end_node_id/source_node_id) and queues their
    real ids for deletion, so the next flush removes the orphan rows too.
    """
    flow = _flow(crew_node_list=[{"id": 100}, {"id": 200}])
    flow["edge_list"] = [
        {"id": 47, "start_node_id": 100, "end_node_id": 200},
        {"id": 48, "start_node_id": 200, "end_node_id": 999},
        {"id": 49, "start_node_id": 300, "end_node_id": 400},
    ]
    flow["conditional_edge_list"] = [
        {"id": 7, "source_node_id": 200},
        {"id": 8, "source_node_id": 300},
    ]
    await service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)

    # Edges referencing the deleted node (either endpoint) are dropped.
    assert snapshot["edge_list"] == [
        {"id": 49, "start_node_id": 300, "end_node_id": 400}
    ]
    assert snapshot["conditional_edge_list"] == [{"id": 8, "source_node_id": 300}]

    # Their real ids are queued for DB deletion.
    assert sorted(snapshot["deleted"]["edge_ids"]) == [47, 48]
    assert snapshot["deleted"]["conditional_edge_ids"] == [7]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_dedupes_edge_id_already_accumulated(service):
    """An edge already queued for deletion by a prior connections_deleted op
    must not be duplicated when a subsequent node delete also cascades to it.
    """
    flow = _flow(crew_node_list=[{"id": 100}, {"id": 200}])
    flow["edge_list"] = [{"id": 47, "start_node_id": 100, "end_node_id": 200}]
    flow["deleted"] = {"edge_ids": [47], "conditional_edge_ids": []}
    await service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)

    assert snapshot["edge_list"] == []
    assert snapshot["deleted"]["edge_ids"] == [47]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_nulls_decision_table_routing_refs(service):
    """Deleting a node clears any decision-table routing ref pointing at it —
    default_next_node_id, next_error_node_id, and per-group next_node_id —
    on both DecisionTableNode and ClassificationDecisionTableNode entries.
    """
    flow = _flow(crew_node_list=[{"id": 200}])
    flow["decision_table_node_list"] = [
        {
            "id": 1,
            "default_next_node_id": 200,
            "next_error_node_id": 300,
            "condition_groups": [
                {"id": 10, "next_node_id": 200},
                {"id": 11, "next_node_id": 400},
            ],
        }
    ]
    flow["classification_decision_table_node_list"] = [
        {"id": 2, "default_next_node_id": 300, "next_error_node_id": 200}
    ]
    await service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=200)],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)

    decision_table = snapshot["decision_table_node_list"][0]
    assert decision_table["default_next_node_id"] is None
    assert decision_table["next_error_node_id"] == 300
    assert decision_table["condition_groups"][0]["next_node_id"] is None
    assert decision_table["condition_groups"][1]["next_node_id"] == 400

    classification_table = snapshot["classification_decision_table_node_list"][0]
    assert classification_table["default_next_node_id"] == 300
    assert classification_table["next_error_node_id"] is None


@pytest.mark.asyncio
async def test_apply_nodes_deleted_temp_only_ref_skips_cascade(service):
    """A temp_id-only delete ref (never persisted) must not attempt cascade —
    it can only match string temp_ids, never a real edge/routing int ref.
    """
    flow = _flow(crew_node_list=[{"temp_id": "new-node"}])
    flow["edge_list"] = [{"id": 1, "start_node_id": 999, "end_node_id": 998}]
    await service.seed(1, flow)

    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", temp_id="new-node")],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)

    assert snapshot["crew_node_list"] == []
    assert snapshot["edge_list"] == [
        {"id": 1, "start_node_id": 999, "end_node_id": 998}
    ]
    assert snapshot["deleted"]["edge_ids"] == []


# ---------------------------------------------------------------------------
# apply_op — connection ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_connection_created_adds_connection(service):
    await service.seed(1, _flow())
    msg = ConnectionCreatedMessage(
        connection={"id": "c1", "source": "n1", "target": "n2"},
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": "c1", "source": "n1", "target": "n2"}]


@pytest.mark.asyncio
async def test_apply_connection_created_upserts_existing(service):
    existing = [{"id": "c1", "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(edge_list=existing))
    msg = ConnectionCreatedMessage(
        connection={"id": "c1", "source": "n1", "target": "n3"},
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["edge_list"]) == 1
    assert snapshot["edge_list"][0]["target"] == "n3"


@pytest.mark.asyncio
async def test_apply_connection_deleted_removes_connection(service):
    connections = [{"id": 1}, {"id": 2}]
    await service.seed(1, _flow(edge_list=connections))
    msg = ConnectionDeletedMessage(
        connection_id=1,
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2}]


@pytest.mark.asyncio
async def test_apply_connections_deleted_removes_batch(service):
    connections = [{"id": 1}, {"id": 2}, {"id": 3}]
    await service.seed(1, _flow(edge_list=connections))
    msg = ConnectionsDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="edge_list", id=1),
            EntryDeleteRef(list_key="edge_list", id=3),
        ],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2}]


@pytest.mark.asyncio
async def test_apply_connection_waypoints_updated_sets_waypoints(service):
    connections = [{"id": 1, "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(edge_list=connections))
    waypoints = [{"x": 10, "y": 20}, {"x": 30, "y": 40}]
    msg = ConnectionWaypointsUpdatedMessage(
        connection_id=1,
        waypoints=waypoints,
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"][0]["waypoints"] == waypoints


# ---------------------------------------------------------------------------
# apply_op — safe no-op on absent snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_op_on_absent_snapshot_is_safe_noop(service):
    msg = NodeCreatedMessage(
        node={"id": "n1"}, list_key="crew_node_list", editor=_editor()
    )
    # Must not raise and must not create a snapshot.
    await service.apply_op(999, msg)
    assert await service.get_snapshot(999) is None


# ---------------------------------------------------------------------------
# seed_from_db — TOCTOU race guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_from_db_not_found_returns_false(service, monkeypatch):
    monkeypatch.setattr(_gss_module, "_load_graph_snapshot", _async_return(None))
    result = await service.seed_from_db(42)
    assert result is False
    assert await service.get_snapshot(42) is None


@pytest.mark.asyncio
async def test_seed_from_db_seeds_when_absent(service, monkeypatch):
    db_snapshot = _flow(crew_node_list=[{"id": 1, "type": "agent"}])
    monkeypatch.setattr(_gss_module, "_load_graph_snapshot", _async_return(db_snapshot))
    result = await service.seed_from_db(7)
    assert result is True
    assert await service.get_snapshot(7) == db_snapshot
    assert service.current_revision(7) == 0


@pytest.mark.asyncio
async def test_seed_from_db_does_not_stomp_concurrently_seeded_snapshot(
    service, monkeypatch
):
    """Regression test for the seed_from_db TOCTOU race (Bug 1).

    Simulates a late racer: a concurrent connection already seeded the graph
    and a client already applied an op on top of it (marker node present).
    The late racer's DB load (patched here) returns a barer snapshot that
    must NOT overwrite the already-seeded live state.
    """
    graph_id = 5

    # Arrange: live snapshot already seeded + a client op applied on top,
    # carrying a distinctive marker node that a stale DB read would not have.
    already_seeded_snapshot = _flow(
        crew_node_list=[
            {"id": 1, "type": "agent"},
            {"temp_id": "marker-node", "type": "agent"},
        ]
    )
    await service.seed(graph_id, already_seeded_snapshot)
    service._revision[graph_id] = 3
    service._flushed_revision[graph_id] = 0

    # The late racer's stale DB read — barer, missing the marker node.
    stale_db_snapshot = _flow(crew_node_list=[{"id": 1, "type": "agent"}])
    monkeypatch.setattr(
        _gss_module, "_load_graph_snapshot", _async_return(stale_db_snapshot)
    )

    # Act
    result = await service.seed_from_db(graph_id)

    # Assert: seed_from_db reports success but must not stomp the live state.
    assert result is True
    snapshot = await service.get_snapshot(graph_id)
    assert snapshot == already_seeded_snapshot
    assert any(
        entry.get("temp_id") == "marker-node" for entry in snapshot["crew_node_list"]
    )
    # Revision counters must be untouched — a stomp would reset both to 0.
    assert service.current_revision(graph_id) == 3
    assert service._flushed_revision[graph_id] == 0


def _async_return(value):
    async def _coro(*_args, **_kwargs):
        return value

    return _coro


# ---------------------------------------------------------------------------
# Retained temp_id -> real_id map (Bug 1b, Option B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_records_resolved_temp_ids(service):
    """Regression test for Bug 1b.

    A node created via WS op carries temp_id "U". Once the flush that
    persists it runs, apply_id_remap stamps id=42 and pops temp_id — but the
    retained temp_id->real_id map must remember U -> 42 so a later edge op
    referencing "U" as an endpoint can still resolve.
    """
    graph_id = 1
    await service.seed(
        graph_id, _flow(crew_node_list=[{"temp_id": "U", "type": "agent"}])
    )

    await service.apply_id_remap(
        graph_id, {"U": 42}, new_save_version=2, flushed_deleted={}
    )

    snapshot = await service.get_snapshot(graph_id)
    assert snapshot["crew_node_list"] == [{"id": 42, "type": "agent"}]
    assert await service.get_resolved_temp_ids(graph_id) == {"U": 42}


@pytest.mark.asyncio
async def test_apply_op_rewrites_edge_endpoint_for_already_remapped_temp_id(service):
    """The core Bug 1b fix: a late edge referencing an already-flushed node's
    temp_id must have its endpoint rewritten to the real id at apply_op time,
    so the next flush resolves cleanly instead of raising
    BulkSaveValidationError.
    """
    graph_id = 1
    await service.seed(
        graph_id, _flow(crew_node_list=[{"temp_id": "U", "type": "agent"}])
    )
    await service.apply_id_remap(
        graph_id, {"U": 42}, new_save_version=2, flushed_deleted={}
    )

    msg = ConnectionCreatedMessage(
        connection={
            "temp_id": "edge-1",
            "start_temp_id": "U",
            "end_node_id": 7,
        },
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(graph_id, msg)

    snapshot = await service.get_snapshot(graph_id)
    assert len(snapshot["edge_list"]) == 1
    edge = snapshot["edge_list"][0]
    assert edge["start_node_id"] == 42
    assert "start_temp_id" not in edge
    # The edge's own temp_id must be untouched by endpoint resolution.
    assert edge["temp_id"] == "edge-1"


@pytest.mark.asyncio
async def test_apply_op_leaves_unresolved_temp_id_endpoint_untouched(service):
    """A new-node flow: the endpoint temp_id has no entry in the retained map
    yet (its node hasn't been flushed), so it must be left as-is for normal
    flush-time resolution via the node's own temp_id.
    """
    graph_id = 1
    await service.seed(graph_id, _flow())

    msg = ConnectionCreatedMessage(
        connection={
            "temp_id": "edge-1",
            "start_temp_id": "not-yet-flushed",
            "end_node_id": 7,
        },
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(graph_id, msg)

    snapshot = await service.get_snapshot(graph_id)
    edge = snapshot["edge_list"][0]
    assert edge["start_temp_id"] == "not-yet-flushed"
    assert "start_node_id" not in edge


@pytest.mark.asyncio
async def test_clear_removes_resolved_temp_ids_map(service):
    graph_id = 1
    await service.seed(graph_id, _flow())
    await service.record_resolved_temp_ids(graph_id, {"U": 42})
    assert await service.get_resolved_temp_ids(graph_id) == {"U": 42}

    await service.clear(graph_id)

    assert await service.get_snapshot(graph_id) is None


# ---------------------------------------------------------------------------
# apply_op — singleton dedup for start_node_list / end_node_list (EST-3020 Bug 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", ["start_node_list", "end_node_list"])
async def test_apply_op_singleton_created_with_mismatched_temp_id_never_appends(
    service, list_key
):
    """Two NodeCreated ops for a singleton list, each carrying a different
    temp_id, must never leave more than one entry in the snapshot — the
    second op replaces the first instead of appending a duplicate.
    """
    graph_id = 1
    await service.seed(graph_id, _flow())

    first_msg = NodeCreatedMessage(
        node={"temp_id": "temp-a"},
        list_key=list_key,
        editor=_editor(),
    )
    await service.apply_op(graph_id, first_msg)

    second_msg = NodeCreatedMessage(
        node={"temp_id": "temp-b"},
        list_key=list_key,
        editor=_editor(),
    )
    await service.apply_op(graph_id, second_msg)

    snapshot = await service.get_snapshot(graph_id)
    assert len(snapshot[list_key]) == 1
    assert snapshot[list_key][0].get("temp_id") == "temp-b"


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", ["start_node_list", "end_node_list"])
async def test_apply_op_singleton_update_without_id_keeps_existing_real_id(
    service, list_key
):
    """When the existing singleton entry carries a real (persisted) id and a
    later Created/Updated op arrives with no id (only a temp_id — e.g. a
    reconnect that regenerated the synthetic node client-side), the real id
    must be preserved on the surviving entry so the next flush treats it as
    an UPDATE, never a duplicate create.
    """
    graph_id = 1
    flow = _flow()
    flow[list_key] = [{"id": 5}]
    await service.seed(graph_id, flow)

    msg = NodeCreatedMessage(
        node={"temp_id": "temp-c"},
        list_key=list_key,
        editor=_editor(),
    )
    await service.apply_op(graph_id, msg)

    snapshot = await service.get_snapshot(graph_id)
    assert len(snapshot[list_key]) == 1
    survivor = snapshot[list_key][0]
    assert survivor["id"] == 5
    assert "temp_id" not in survivor
    assert await service.get_resolved_temp_ids(graph_id) == {}
