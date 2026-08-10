"""
Unit tests for GraphLiveStateService.apply_id_remap.

Redis is replaced with fakeredis.aioredis via the autouse patch_graph_state_redis
fixture from conftest.py.  No DB needed for these tests.
"""

import pytest

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab.graph_state_service import graph_state_service


@pytest.fixture(autouse=True)
def noop_content_hash_refresh(monkeypatch):
    """These tests exercise apply_id_remap's temp_id/edge/orphan/deleted-
    accumulator logic in isolation, with fake ids (10, 42, 99, ...) that do
    not correspond to real DB rows. Patch out the content_hash DB refresh
    step (EST-3020, see _refresh_flushed_content_hashes) so this file stays
    DB-free, matching its original scope. Dedicated DB-backed coverage for
    the refresh itself lives in test_content_hash_refresh.py.
    """

    async def _noop(snapshot):
        return None

    monkeypatch.setattr(_gss_module, "_refresh_flushed_content_hashes", _noop)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_deleted() -> dict:
    return {
        "edge_ids": [],
        "conditional_edge_ids": [],
        "crew_node_ids": [],
        "python_node_ids": [],
        "file_extractor_node_ids": [],
        "audio_transcription_node_ids": [],
        "start_node_ids": [],
        "end_node_ids": [],
        "subgraph_node_ids": [],
        "decision_table_node_ids": [],
        "graph_note_ids": [],
        "webhook_trigger_node_ids": [],
        "telegram_trigger_node_ids": [],
        "schedule_trigger_node_ids": [],
        "code_agent_node_ids": [],
        "classification_decision_table_node_ids": [],
    }


def _snapshot(**overrides) -> dict:
    base = {
        "save_version": 1,
        "crew_node_list": [],
        "python_node_list": [],
        "file_extractor_node_list": [],
        "audio_transcription_node_list": [],
        "start_node_list": [],
        "end_node_list": [],
        "subgraph_node_list": [],
        "decision_table_node_list": [],
        "graph_note_list": [],
        "webhook_trigger_node_list": [],
        "telegram_trigger_node_list": [],
        "schedule_trigger_node_list": [],
        "code_agent_node_list": [],
        "edge_list": [],
        "conditional_edge_list": [],
        "deleted": _empty_deleted(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# No-op when no snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_no_snapshot_is_noop():
    """apply_id_remap must not raise and must not create a snapshot."""
    await graph_state_service.apply_id_remap(
        9999, {"tmp-a": 1}, new_save_version=2, flushed_deleted=_empty_deleted()
    )
    assert await graph_state_service.get_snapshot(9999) is None


# ---------------------------------------------------------------------------
# Node temp_id → real id rewrite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_node_temp_id():
    """A node entry with temp_id in the map gets id set and temp_id removed."""
    snap = _snapshot(
        python_node_list=[
            {"temp_id": "tmp-1", "node_name": "my_node"},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {"tmp-1": 42}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    node = result["python_node_list"][0]
    assert node["id"] == 42
    assert "temp_id" not in node
    assert node["node_name"] == "my_node"


@pytest.mark.asyncio
async def test_apply_id_remap_leaves_nodes_with_real_id_untouched():
    """Nodes that already have a real id and no temp_id must not be touched."""
    snap = _snapshot(
        crew_node_list=[
            {"id": 10, "crew_id": 5, "node_name": "existing"},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    node = result["crew_node_list"][0]
    assert node["id"] == 10
    assert "temp_id" not in node


@pytest.mark.asyncio
async def test_apply_id_remap_multiple_nodes_across_lists():
    """Remapping works across multiple node type lists in a single call."""
    snap = _snapshot(
        python_node_list=[{"temp_id": "tmp-py-1", "node_name": "py"}],
        crew_node_list=[{"temp_id": "tmp-cr-1", "crew_id": 3}],
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1,
        {"tmp-py-1": 100, "tmp-cr-1": 200},
        new_save_version=3,
        flushed_deleted=_empty_deleted(),
    )

    result = await graph_state_service.get_snapshot(1)
    assert result["python_node_list"][0]["id"] == 100
    assert "temp_id" not in result["python_node_list"][0]
    assert result["crew_node_list"][0]["id"] == 200
    assert "temp_id" not in result["crew_node_list"][0]


@pytest.mark.asyncio
async def test_apply_id_remap_temp_id_not_in_map_left_as_is():
    """A node with a temp_id that is NOT in the map is left unchanged."""
    snap = _snapshot(
        python_node_list=[{"temp_id": "tmp-unknown", "node_name": "unresolved"}],
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {"tmp-other": 77}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    node = result["python_node_list"][0]
    assert node.get("temp_id") == "tmp-unknown"
    assert "id" not in node


# ---------------------------------------------------------------------------
# Edge temp ref rewrites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_edge_start_temp_id():
    """start_temp_id on an edge entry is rewritten to start_node_id."""
    snap = _snapshot(
        edge_list=[
            {"start_temp_id": "tmp-n1", "end_node_id": 20},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {"tmp-n1": 10}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 10
    assert "start_temp_id" not in edge
    assert edge["end_node_id"] == 20


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_edge_end_temp_id():
    """end_temp_id on an edge entry is rewritten to end_node_id."""
    snap = _snapshot(
        edge_list=[
            {"start_node_id": 10, "end_temp_id": "tmp-n2"},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {"tmp-n2": 20}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["end_node_id"] == 20
    assert "end_temp_id" not in edge
    assert edge["start_node_id"] == 10


@pytest.mark.asyncio
async def test_apply_id_remap_rewrites_conditional_edge_source_temp_id():
    """source_temp_id on a conditional edge is rewritten to source_node_id."""
    snap = _snapshot(
        conditional_edge_list=[
            {"source_temp_id": "tmp-src", "label": "yes"},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {"tmp-src": 55}, new_save_version=2, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    cond_edge = result["conditional_edge_list"][0]
    assert cond_edge["source_node_id"] == 55
    assert "source_temp_id" not in cond_edge
    assert cond_edge["label"] == "yes"


@pytest.mark.asyncio
async def test_apply_id_remap_edge_with_both_temp_refs():
    """Both start_temp_id and end_temp_id on the same edge are rewritten."""
    snap = _snapshot(
        edge_list=[
            {"start_temp_id": "tmp-a", "end_temp_id": "tmp-b"},
        ]
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1,
        {"tmp-a": 11, "tmp-b": 22},
        new_save_version=2,
        flushed_deleted=_empty_deleted(),
    )

    result = await graph_state_service.get_snapshot(1)
    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 11
    assert edge["end_node_id"] == 22
    assert "start_temp_id" not in edge
    assert "end_temp_id" not in edge


# ---------------------------------------------------------------------------
# save_version bump
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_bumps_save_version():
    """save_version in the snapshot is replaced with new_save_version."""
    snap = _snapshot(save_version=5)
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1, {}, new_save_version=6, flushed_deleted=_empty_deleted()
    )

    result = await graph_state_service.get_snapshot(1)
    assert result["save_version"] == 6


# ---------------------------------------------------------------------------
# deleted accumulator cleared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_clears_deleted_accumulator():
    """The deleted accumulator is reset to all-empty lists after a flush."""
    snap = _snapshot(
        python_node_list=[],
        deleted={
            **_empty_deleted(),
            "python_node_ids": [7, 8, 9],
            "edge_ids": [3],
        },
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1,
        {},
        new_save_version=2,
        flushed_deleted={
            **_empty_deleted(),
            "python_node_ids": [7, 8, 9],
            "edge_ids": [3],
        },
    )

    result = await graph_state_service.get_snapshot(1)
    deleted = result["deleted"]
    assert deleted["python_node_ids"] == []
    assert deleted["edge_ids"] == []
    # Other keys should also be empty.
    for ids in deleted.values():
        assert ids == []


# ---------------------------------------------------------------------------
# Combined: node + edge remap in one call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_combined_node_and_edge():
    """Remap a new python node and an edge referencing it, all in one call."""
    snap = _snapshot(
        python_node_list=[{"temp_id": "tmp-py", "node_name": "new_node"}],
        edge_list=[{"start_temp_id": "tmp-py", "end_node_id": 99}],
        deleted={**_empty_deleted(), "crew_node_ids": [1]},
    )
    await graph_state_service.seed(1, snap)

    await graph_state_service.apply_id_remap(
        1,
        {"tmp-py": 50},
        new_save_version=4,
        flushed_deleted={**_empty_deleted(), "crew_node_ids": [1]},
    )

    result = await graph_state_service.get_snapshot(1)

    node = result["python_node_list"][0]
    assert node["id"] == 50
    assert "temp_id" not in node

    edge = result["edge_list"][0]
    assert edge["start_node_id"] == 50
    assert "start_temp_id" not in edge
    assert edge["end_node_id"] == 99

    assert result["save_version"] == 4
    assert result["deleted"]["crew_node_ids"] == []


# ---------------------------------------------------------------------------
# FIX 2: Precise deleted-accumulator reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_precise_deleted_removes_only_flushed_ids():
    """Only ids present in flushed_deleted are removed from the live accumulator.

    Scenario:
    - Live accumulator has crew_node_ids = [10, 11].
    - flushed_deleted has crew_node_ids = [10]  (only id=10 was persisted).
    - After remap: accumulator must have [11] (id=10 removed, id=11 kept).
    """
    snap = _snapshot(
        deleted={**_empty_deleted(), "crew_node_ids": [10, 11]},
    )
    await graph_state_service.seed(1, snap)

    flushed_deleted = {**_empty_deleted(), "crew_node_ids": [10]}
    await graph_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=flushed_deleted
    )

    result = await graph_state_service.get_snapshot(1)
    # id=11 must be preserved; id=10 was flushed and must be removed.
    assert result["deleted"]["crew_node_ids"] == [11]


@pytest.mark.asyncio
async def test_apply_id_remap_precise_deleted_preserves_concurrent_delete():
    """An id accumulated after the flush read-point is NOT removed.

    This is the core data-correctness guarantee of FIX 2: a concurrent
    apply_op delete (id=11) added between flush-read and remap must survive.
    """
    snap = _snapshot(
        deleted={**_empty_deleted(), "crew_node_ids": [10, 11]},
    )
    await graph_state_service.seed(1, snap)

    # Only id=10 was in the snapshot when the flush read it.
    flushed_deleted = {**_empty_deleted(), "crew_node_ids": [10]}
    await graph_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=flushed_deleted
    )

    result = await graph_state_service.get_snapshot(1)
    assert 11 in result["deleted"]["crew_node_ids"]
    assert 10 not in result["deleted"]["crew_node_ids"]


@pytest.mark.asyncio
async def test_apply_id_remap_precise_deleted_multiple_types():
    """Precise reconciliation works across multiple accumulator keys simultaneously."""
    snap = _snapshot(
        deleted={
            **_empty_deleted(),
            "crew_node_ids": [1, 2],
            "edge_ids": [5, 6],
        },
    )
    await graph_state_service.seed(1, snap)

    # Flush persisted crew_node_ids=[1] and edge_ids=[5].
    flushed_deleted = {**_empty_deleted(), "crew_node_ids": [1], "edge_ids": [5]}
    await graph_state_service.apply_id_remap(
        1, {}, new_save_version=2, flushed_deleted=flushed_deleted
    )

    result = await graph_state_service.get_snapshot(1)
    assert result["deleted"]["crew_node_ids"] == [2]
    assert result["deleted"]["edge_ids"] == [6]


# ---------------------------------------------------------------------------
# FIX 3: Orphan node detection after in-flight delete of a freshly-created node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_orphan_temp_node_enqueued_for_deletion():
    """If a temp node was in the flushed snapshot but is gone from the live snapshot,
    its real id must be enqueued in the deleted accumulator.

    Scenario:
    1. Flushed snapshot had temp node tmp-1 which was assigned real id=42.
    2. Between flush and remap, apply_op deleted tmp-1 (live snapshot has no such node).
    3. temp_id_map = {"tmp-1": 42}.
    4. After remap: crew_node_ids accumulator must contain 42.
    """
    # Live snapshot has NO node with temp_id "tmp-1" — it was concurrently deleted.
    snap = _snapshot(crew_node_list=[])
    await graph_state_service.seed(1, snap)

    # The flushed snapshot had a node with temp_id "tmp-1" under crew_node_list.
    # We pass flushed_deleted as empty (the concurrent delete was not flushed).
    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-1": "crew_node_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-1": 42},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    # Real id=42 must now be queued for deletion.
    assert 42 in result["deleted"]["crew_node_ids"]


@pytest.mark.asyncio
async def test_apply_id_remap_non_orphan_node_not_enqueued():
    """A node that IS still in the live snapshot (survived the flush cycle) must
    NOT be added to the deleted accumulator.

    This ensures FIX 3 only targets genuinely missing nodes.
    """
    # Live snapshot has the node with temp_id "tmp-1" (it was NOT deleted).
    snap = _snapshot(
        python_node_list=[{"temp_id": "tmp-1", "node_name": "alive"}],
    )
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-1": "python_node_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-1": 99},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    # Node survived — must NOT be in the deleted accumulator.
    assert 99 not in result["deleted"]["python_node_ids"]
    # And it must have been remapped normally.
    assert result["python_node_list"][0]["id"] == 99


@pytest.mark.asyncio
async def test_apply_id_remap_orphan_node_multi_type():
    """Orphan detection works for python_node_list as well (not only crew_node_list)."""
    # Live snapshot lacks the python node that was created during flush.
    snap = _snapshot(python_node_list=[])
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-py-x": "python_node_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-py-x": 77},
        new_save_version=3,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    assert 77 in result["deleted"]["python_node_ids"]


# ---------------------------------------------------------------------------
# Regression: edges/conditional edges have their own temp_id (self-stamped by
# apply_id_remap after the flush that first creates them) and must be routed
# through the same orphan-detection path as nodes when deleted in the window
# between that flush and the next one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_id_remap_orphan_edge_enqueued_for_deletion():
    """A newly-created edge deleted before the next flush must not be orphaned.

    Scenario (the exact race from the EST-3020 follow-up review):
    1. An edge with temp_id "tmp-edge-1" was flushed and assigned real id=123.
    2. Before the NEXT flush, the edge is removed from the live snapshot
       (e.g. a ConnectionDeletedMessage arrived).
    3. temp_id_map = {"tmp-edge-1": 123} — as apply_id_remap would build it
       when GraphFlushService includes edge_list in
       flushed_temp_id_to_list_key.
    4. After remap: edge_ids accumulator must contain 123 so the next flush
       actually deletes the orphaned DB row, instead of leaving it stranded.
    """
    # Live snapshot has NO edge with temp_id "tmp-edge-1" — it was concurrently deleted.
    snap = _snapshot(edge_list=[])
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-edge-1": "edge_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-edge-1": 123},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    assert 123 in result["deleted"]["edge_ids"]


@pytest.mark.asyncio
async def test_apply_id_remap_orphan_conditional_edge_enqueued_for_deletion():
    """Same orphan-detection guarantee as above, for a conditional edge."""
    snap = _snapshot(conditional_edge_list=[])
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-cond-edge-1": "conditional_edge_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-cond-edge-1": 456},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    assert 456 in result["deleted"]["conditional_edge_ids"]


@pytest.mark.asyncio
async def test_apply_id_remap_non_orphan_edge_not_enqueued_and_id_stamped():
    """An edge that IS still in the live snapshot must not be misdetected as an
    orphan, and its own id must be stamped from its own temp_id (distinct from
    the start/end node reference fields on the same entry).
    """
    snap = _snapshot(
        edge_list=[
            {
                "temp_id": "tmp-edge-1",
                "start_node_id": 1,
                "end_node_id": 2,
            }
        ],
    )
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-edge-1": "edge_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-edge-1": 123},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    # Edge survived — must NOT be in the deleted accumulator.
    assert 123 not in result["deleted"]["edge_ids"]
    # And its own id must have been stamped normally.
    edge = result["edge_list"][0]
    assert edge["id"] == 123
    assert "temp_id" not in edge


@pytest.mark.asyncio
async def test_apply_id_remap_non_orphan_conditional_edge_not_enqueued_and_id_stamped():
    """Same non-orphan guarantee as above, for a conditional edge."""
    snap = _snapshot(
        conditional_edge_list=[
            {
                "temp_id": "tmp-cond-edge-1",
                "source_node_id": 1,
                "label": "yes",
            }
        ],
    )
    await graph_state_service.seed(1, snap)

    flushed_deleted = _empty_deleted()
    flushed_temp_id_to_list_key = {"tmp-cond-edge-1": "conditional_edge_list"}
    await graph_state_service.apply_id_remap(
        1,
        {"tmp-cond-edge-1": 456},
        new_save_version=2,
        flushed_deleted=flushed_deleted,
        flushed_temp_id_to_list_key=flushed_temp_id_to_list_key,
    )

    result = await graph_state_service.get_snapshot(1)
    assert 456 not in result["deleted"]["conditional_edge_ids"]
    cond_edge = result["conditional_edge_list"][0]
    assert cond_edge["id"] == 456
    assert "temp_id" not in cond_edge
