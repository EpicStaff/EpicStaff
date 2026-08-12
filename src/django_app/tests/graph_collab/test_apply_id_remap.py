"""
Unit tests for GraphLiveStateService.apply_id_remap.

Redis is replaced with fakeredis.aioredis via the autouse patch_graph_state_redis
fixture from conftest.py.  No DB needed for these tests.
"""

import pytest

from tables.graph_collab.constants import _DECISION_TABLE_LIST_KEYS

pytestmark = pytest.mark.usefixtures("noop_content_hash_refresh")


# ---------------------------------------------------------------------------
# No-op when no snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_no_snapshot_is_noop(live_state_service, empty_deleted):
    """apply_id_remap must not raise and must not create a snapshot."""
    await live_state_service.apply_id_remap(
        9999, {"tmp-a": 1}, new_save_version=2, flushed_deleted=empty_deleted()
    )
    assert await live_state_service.get_snapshot(9999) is None


# ---------------------------------------------------------------------------
# Node temp_id → real id rewrite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_node_temp_id(
    live_state_service, base_snapshot, empty_deleted
):
    """A node entry with temp_id in the map gets id set and temp_id removed."""
    snap = base_snapshot(
        python_node_list=[
            {"temp_id": "tmp-1", "node_name": "my_node"},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-1": 42}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    node = result["python_node_list"][0]
    assert node["id"] == 42
    assert "temp_id" not in node
    assert node["node_name"] == "my_node"


@pytest.mark.asyncio
async def test_apply_id_remap_leaves_nodes_with_real_id_untouched(
    live_state_service, base_snapshot, empty_deleted
):
    """Nodes that already have a real id and no temp_id must not be touched."""
    snap = base_snapshot(
        crew_node_list=[
            {"id": 10, "crew_id": 5, "node_name": "existing"},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    node = result["crew_node_list"][0]
    assert node["id"] == 10
    assert "temp_id" not in node


@pytest.mark.asyncio
async def test_apply_id_remap_multiple_nodes_across_lists(
    live_state_service, base_snapshot, empty_deleted
):
    """Remapping works across multiple node type lists in a single call."""
    snap = base_snapshot(
        python_node_list=[{"temp_id": "tmp-py-1", "node_name": "py"}],
        crew_node_list=[{"temp_id": "tmp-cr-1", "crew_id": 3}],
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1,
        {"tmp-py-1": 100, "tmp-cr-1": 200},
        new_save_version=3,
        flushed_deleted=empty_deleted(),
    )

    result = await live_state_service.get_snapshot(1)
    assert result["python_node_list"][0]["id"] == 100
    assert "temp_id" not in result["python_node_list"][0]
    assert result["crew_node_list"][0]["id"] == 200
    assert "temp_id" not in result["crew_node_list"][0]


@pytest.mark.asyncio
async def test_apply_id_remap_temp_id_not_in_map_left_as_is(
    live_state_service, base_snapshot, empty_deleted
):
    """A node with a temp_id that is NOT in the map is left unchanged."""
    snap = base_snapshot(
        python_node_list=[{"temp_id": "tmp-unknown", "node_name": "unresolved"}],
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-other": 77}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    node = result["python_node_list"][0]
    assert node.get("temp_id") == "tmp-unknown"
    assert "id" not in node


@pytest.mark.asyncio
async def test_apply_id_remap_survivor_and_orphan_coexist(
    live_state_service, base_snapshot, empty_deleted
):
    """When a flushed snapshot had two temp entries and only one survives to the
    live snapshot, the survivor is stamped and the concurrently-deleted one is
    enqueued for deletion — without the survivor's real id leaking into that
    accumulator.
    """
    snap = base_snapshot(
        python_node_list=[{"temp_id": "tmp-survivor", "node_name": "alive"}],
    )
    await live_state_service.seed(1, snap)

    temp_id_map = {"tmp-survivor": 42, "tmp-deleted": 77}
    flushed_temp_id_to_list_key = {
        "tmp-survivor": "python_node_list",
        "tmp-deleted": "python_node_list",
    }
    await live_state_service.apply_id_remap(
        1,
        temp_id_map,
        new_save_version=2,
        flushed_deleted=empty_deleted(),
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await live_state_service.get_snapshot(1)
    survivor = result["python_node_list"][0]
    assert survivor["id"] == 42
    assert "temp_id" not in survivor

    assert 77 in result["deleted"]["python_node_ids"]
    assert 42 not in result["deleted"]["python_node_ids"]


# ---------------------------------------------------------------------------
# Edge temp ref rewrites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_edge_start_temp_id(
    live_state_service, base_snapshot, empty_deleted
):
    """start_temp_id is rewritten to start_node_id; an already-real end_node_id
    on the same edge is left untouched."""
    snap = base_snapshot(
        edge_list=[
            {"start_temp_id": "tmp-n1", "end_node_id": 20},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-n1": 10}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 10
    assert "start_temp_id" not in edge
    assert edge["end_node_id"] == 20


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_edge_end_temp_id(
    live_state_service, base_snapshot, empty_deleted
):
    """end_temp_id is rewritten to end_node_id; an already-real start_node_id
    on the same edge is left untouched."""
    snap = base_snapshot(
        edge_list=[
            {"start_node_id": 10, "end_temp_id": "tmp-n2"},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-n2": 20}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["end_node_id"] == 20
    assert "end_temp_id" not in edge
    assert edge["start_node_id"] == 10


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_conditional_edge_source_temp_id(
    live_state_service, base_snapshot, empty_deleted
):
    """source_temp_id on a conditional edge is rewritten to source_node_id."""
    snap = base_snapshot(
        conditional_edge_list=[
            {"source_temp_id": "tmp-src", "label": "yes"},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-src": 55}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    cond_edge = result["conditional_edge_list"][0]
    assert cond_edge["source_node_id"] == 55
    assert "source_temp_id" not in cond_edge
    assert cond_edge["label"] == "yes"


@pytest.mark.asyncio
async def test_apply_id_remap_edge_with_both_temp_refs(
    live_state_service, base_snapshot, empty_deleted
):
    """When neither endpoint was persisted yet, both start_temp_id and
    end_temp_id on the same edge are rewritten."""
    snap = base_snapshot(
        edge_list=[
            {"start_temp_id": "tmp-a", "end_temp_id": "tmp-b"},
        ]
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1,
        {"tmp-a": 11, "tmp-b": 22},
        new_save_version=2,
        flushed_deleted=empty_deleted(),
    )

    result = await live_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 11
    assert edge["end_node_id"] == 22
    assert "start_temp_id" not in edge
    assert "end_temp_id" not in edge


# ---------------------------------------------------------------------------
# Decision-table routing ref rewrites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_key",
    _DECISION_TABLE_LIST_KEYS,
    ids=list(_DECISION_TABLE_LIST_KEYS),
)
async def test_apply_id_remap_rewrites_decision_table_routing_refs(
    live_state_service, base_snapshot, empty_deleted, list_key
):
    """default_next_node_temp_id, next_error_node_temp_id, and every
    condition_groups[].next_node_temp_id are rewritten to their real-id
    counterparts, for both decision-table list types."""
    snap = base_snapshot(
        **{
            list_key: [
                {
                    "id": 1,
                    "default_next_node_temp_id": "tmp-default",
                    "next_error_node_temp_id": "tmp-error",
                    "condition_groups": [
                        {"id": 10, "next_node_temp_id": "tmp-group-a"},
                        {"id": 11, "next_node_temp_id": "tmp-group-b"},
                    ],
                }
            ]
        }
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1,
        {
            "tmp-default": 200,
            "tmp-error": 300,
            "tmp-group-a": 400,
            "tmp-group-b": 500,
        },
        new_save_version=2,
        flushed_deleted=empty_deleted(),
    )

    result = await live_state_service.get_snapshot(1)
    entry = result[list_key][0]
    assert entry["default_next_node_id"] == 200
    assert "default_next_node_temp_id" not in entry
    assert entry["next_error_node_id"] == 300
    assert "next_error_node_temp_id" not in entry
    assert entry["condition_groups"][0]["next_node_id"] == 400
    assert "next_node_temp_id" not in entry["condition_groups"][0]
    assert entry["condition_groups"][1]["next_node_id"] == 500
    assert "next_node_temp_id" not in entry["condition_groups"][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_key",
    _DECISION_TABLE_LIST_KEYS,
    ids=list(_DECISION_TABLE_LIST_KEYS),
)
async def test_apply_id_remap_decision_table_unmapped_refs_left_as_is(
    live_state_service, base_snapshot, empty_deleted, list_key
):
    """Routing refs whose temp id is absent from temp_id_map are left
    untouched — an unresolved ref must never be replaced with a fabricated
    real id."""
    snap = base_snapshot(
        **{
            list_key: [
                {
                    "id": 1,
                    "default_next_node_temp_id": "tmp-unknown",
                    "next_error_node_temp_id": "tmp-also-unknown",
                    "condition_groups": [
                        {"id": 10, "next_node_temp_id": "tmp-group-unknown"},
                    ],
                }
            ]
        }
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {"tmp-other": 999}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    entry = result[list_key][0]
    assert entry["default_next_node_temp_id"] == "tmp-unknown"
    assert "default_next_node_id" not in entry
    assert entry["next_error_node_temp_id"] == "tmp-also-unknown"
    assert "next_error_node_id" not in entry
    group = entry["condition_groups"][0]
    assert group["next_node_temp_id"] == "tmp-group-unknown"
    assert "next_node_id" not in group


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_key",
    _DECISION_TABLE_LIST_KEYS,
    ids=list(_DECISION_TABLE_LIST_KEYS),
)
async def test_apply_id_remap_decision_table_skips_malformed_entries(
    live_state_service, base_snapshot, empty_deleted, list_key
):
    """An entry with condition_groups explicitly None and a non-dict group
    must not crash the remap, and must not stop a well-formed sibling entry
    from being remapped correctly."""
    snap = base_snapshot(
        **{
            list_key: [
                {
                    "id": 2,
                    "default_next_node_temp_id": "tmp-no-groups",
                    "condition_groups": None,
                },
                {
                    "id": 3,
                    "next_error_node_temp_id": "tmp-bad-group",
                    "condition_groups": ["not-a-dict"],
                },
                {"id": 4, "default_next_node_temp_id": "tmp-good"},
            ]
        }
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1,
        {"tmp-no-groups": 100, "tmp-bad-group": 200, "tmp-good": 300},
        new_save_version=2,
        flushed_deleted=empty_deleted(),
    )

    result = await live_state_service.get_snapshot(1)
    entries = result[list_key]
    assert entries[0]["default_next_node_id"] == 100
    assert entries[1]["next_error_node_id"] == 200
    assert entries[1]["condition_groups"] == ["not-a-dict"]
    assert entries[2]["default_next_node_id"] == 300
    assert "default_next_node_temp_id" not in entries[2]


# ---------------------------------------------------------------------------
# save_version bump
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_bumps_save_version(
    live_state_service, base_snapshot, empty_deleted
):
    """save_version in the snapshot is replaced with new_save_version."""
    snap = base_snapshot(save_version=5)
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1, {}, new_save_version=6, flushed_deleted=empty_deleted()
    )

    result = await live_state_service.get_snapshot(1)
    assert result["save_version"] == 6


# ---------------------------------------------------------------------------
# Combined: node + edge remap in one call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_combined_node_and_edge(
    live_state_service, base_snapshot, empty_deleted
):
    """Remap a new python node, an edge, and a conditional edge all referencing
    that node, in one call."""
    snap = base_snapshot(
        python_node_list=[{"temp_id": "tmp-py", "node_name": "new_node"}],
        edge_list=[{"start_temp_id": "tmp-py", "end_node_id": 99}],
        conditional_edge_list=[{"source_temp_id": "tmp-py", "label": "yes"}],
        deleted={**empty_deleted(), "crew_node_ids": [1]},
    )
    await live_state_service.seed(1, snap)

    await live_state_service.apply_id_remap(
        1,
        {"tmp-py": 50},
        new_save_version=4,
        flushed_deleted={**empty_deleted(), "crew_node_ids": [1]},
    )

    result = await live_state_service.get_snapshot(1)

    node = result["python_node_list"][0]
    assert node["id"] == 50
    assert "temp_id" not in node

    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 50
    assert "start_temp_id" not in edge
    assert edge["end_node_id"] == 99

    cond_edge = result["conditional_edge_list"][0]
    assert cond_edge["source_node_id"] == 50
    assert "source_temp_id" not in cond_edge

    assert result["save_version"] == 4
    assert result["deleted"]["crew_node_ids"] == []


# ---------------------------------------------------------------------------
# Precise deleted-accumulator reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_precise_deleted_removes_only_flushed_ids(
    live_state_service, base_snapshot, empty_deleted
):
    """Only ids present in flushed_deleted are removed from the live accumulator;
    an id accumulated after the flush read-point (a concurrent delete) survives.

    Scenario:
    - Live accumulator has crew_node_ids = [10, 11].
    - flushed_deleted has crew_node_ids = [10]  (only id=10 was persisted).
    - After remap: accumulator must have [11] (id=10 removed, id=11 kept).
    """
    snap = base_snapshot(
        deleted={**empty_deleted(), "crew_node_ids": [10, 11]},
    )
    await live_state_service.seed(1, snap)

    flushed_deleted = {**empty_deleted(), "crew_node_ids": [10]}
    await live_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=flushed_deleted
    )

    result = await live_state_service.get_snapshot(1)
    # id=11 must be preserved; id=10 was flushed and must be removed.
    assert result["deleted"]["crew_node_ids"] == [11]


@pytest.mark.asyncio
async def test_apply_id_remap_precise_deleted_multiple_types(
    live_state_service, base_snapshot, empty_deleted
):
    """Precise reconciliation works across multiple accumulator keys simultaneously."""
    snap = base_snapshot(
        deleted={
            **empty_deleted(),
            "crew_node_ids": [1, 2],
            "edge_ids": [5, 6],
        },
    )
    await live_state_service.seed(1, snap)

    # Flush persisted crew_node_ids=[1] and edge_ids=[5].
    flushed_deleted = {**empty_deleted(), "crew_node_ids": [1], "edge_ids": [5]}
    await live_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=flushed_deleted
    )

    result = await live_state_service.get_snapshot(1)
    assert result["deleted"]["crew_node_ids"] == [2]
    assert result["deleted"]["edge_ids"] == [6]


# ---------------------------------------------------------------------------
# Orphan detection after in-flight delete of a freshly-created node/edge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_key,temp_id,real_id,new_save_version,delete_key",
    [
        pytest.param(
            "crew_node_list",
            "tmp-1",
            42,
            2,
            "crew_node_ids",
            id="crew_node_list",
        ),
        pytest.param(
            "python_node_list",
            "tmp-py-x",
            77,
            3,
            "python_node_ids",
            id="python_node_list",
        ),
        pytest.param(
            "edge_list",
            "tmp-edge-1",
            123,
            2,
            "edge_ids",
            id="edge_list",
        ),
        pytest.param(
            "conditional_edge_list",
            "tmp-cond-edge-1",
            456,
            2,
            "conditional_edge_ids",
            id="conditional_edge_list",
        ),
    ],
)
async def test_apply_id_remap_orphan_entry_enqueued_for_deletion(
    live_state_service,
    base_snapshot,
    empty_deleted,
    list_key,
    temp_id,
    real_id,
    new_save_version,
    delete_key,
):
    """A temp entry that was in the flushed snapshot but is gone from the live
    snapshot (concurrently deleted before this remap) has its real id enqueued
    for deletion, for every node and edge list type.
    """
    # Live snapshot has NO entry with this temp_id — it was concurrently deleted.
    snap = base_snapshot()
    await live_state_service.seed(1, snap)

    flushed_deleted = empty_deleted()
    flushed_temp_id_to_list_key = {temp_id: list_key}
    await live_state_service.apply_id_remap(
        1,
        {temp_id: real_id},
        new_save_version=new_save_version,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await live_state_service.get_snapshot(1)
    assert real_id in result["deleted"][delete_key]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "list_key,seeded_entry,temp_id,real_id,delete_key",
    [
        pytest.param(
            "python_node_list",
            {"temp_id": "tmp-1", "node_name": "alive"},
            "tmp-1",
            99,
            "python_node_ids",
            id="python_node_list",
        ),
        pytest.param(
            "edge_list",
            {"temp_id": "tmp-edge-1", "start_node_id": 1, "end_node_id": 2},
            "tmp-edge-1",
            123,
            "edge_ids",
            id="edge_list",
        ),
        pytest.param(
            "conditional_edge_list",
            {"temp_id": "tmp-cond-edge-1", "source_node_id": 1, "label": "yes"},
            "tmp-cond-edge-1",
            456,
            "conditional_edge_ids",
            id="conditional_edge_list",
        ),
    ],
)
async def test_apply_id_remap_non_orphan_entry_stamped_not_enqueued(
    live_state_service,
    base_snapshot,
    empty_deleted,
    list_key,
    seeded_entry,
    temp_id,
    real_id,
    delete_key,
):
    """An entry that IS still in the live snapshot (survived the flush cycle)
    must not be added to the deleted accumulator, and is instead stamped with
    its real id — for every node and edge list type.
    """
    snap = base_snapshot(**{list_key: [seeded_entry]})
    await live_state_service.seed(1, snap)

    flushed_deleted = empty_deleted()
    flushed_temp_id_to_list_key = {temp_id: list_key}
    await live_state_service.apply_id_remap(
        1,
        {temp_id: real_id},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await live_state_service.get_snapshot(1)
    # Entry survived — must NOT be in the deleted accumulator.
    assert real_id not in result["deleted"][delete_key]
    # And it must have been stamped with its real id normally.
    entry = result[list_key][0]
    assert entry["id"] == real_id
    assert "temp_id" not in entry


# ---------------------------------------------------------------------------
# Resolved temp_id map pruning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_leaves_resolved_temp_ids_untouched_when_nothing_flushed_deleted(
    live_state_service, base_snapshot, empty_deleted
):
    """An empty flushed_deleted must leave the resolved temp_id map completely
    unchanged — guards against replacing the targeted prune with a blanket clear.
    """
    snap = base_snapshot()
    await live_state_service.seed(1, snap)
    await live_state_service.record_resolved_temp_ids(1, {"tmp-a": 1, "tmp-b": 2})

    await live_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=empty_deleted()
    )

    resolved = await live_state_service.get_resolved_temp_ids(1)
    assert resolved == {"tmp-a": 1, "tmp-b": 2}
