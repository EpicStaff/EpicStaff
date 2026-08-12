"""Integration tests for GraphFlushService. DB-backed tests require a live
PostgreSQL instance and are marked with @pytest.mark.django_db.
"""

import pytest

from tables.graph_collab.flush_service import (
    FlushOutcome,
    FlushResult,
    FlushStatus,
    GraphFlushService,
    flush_service,
)
from tables.graph_collab.graph_state_service import graph_state_service
from tests.graph_collab.conftest import PYTHON_CODE_DATA, count_nodes, first_node


# ---------------------------------------------------------------------------
# No snapshot → NOTHING_TO_FLUSH (no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_returns_nothing_to_flush_when_no_snapshot(flush_service):
    """flush() returns NOTHING_TO_FLUSH when no live snapshot exists for the graph."""
    outcome = await flush_service.flush(graph_id=99999)
    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.NOTHING_TO_FLUSH
    assert outcome.result is None
    assert not outcome.saved
    assert outcome.safe_to_clear


# ---------------------------------------------------------------------------
# flush_service singleton exists
# ---------------------------------------------------------------------------


def test_flush_service_singleton_is_correct_type():
    assert isinstance(flush_service, GraphFlushService)


# ---------------------------------------------------------------------------
# flush_if_dirty skips when clean
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_if_dirty_skips_when_clean(
    live_state_service, base_snapshot, flush_service, monkeypatch
):
    graph_id = 2
    await live_state_service.seed(graph_id, base_snapshot())
    live_state_service._revision[graph_id] = 0
    live_state_service._flushed_revision[graph_id] = 0

    # Point flush_service internals at our isolated service instance.
    monkeypatch.setattr(
        "tables.graph_collab.flush_service.graph_state_service", live_state_service
    )

    flush_called = []
    original_flush = flush_service.flush

    async def _spy_flush(gid):
        flush_called.append(gid)
        return await original_flush(gid)

    monkeypatch.setattr(flush_service, "flush", _spy_flush)

    outcome = await flush_service.flush_if_dirty(graph_id)

    assert outcome.status is FlushStatus.NOTHING_TO_FLUSH
    assert flush_called == [], "flush() must not be called when snapshot is clean"


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_happy_path_new_node_returns_flush_result(
    graph, base_snapshot, flush_service
):
    """Happy path: snapshot with one new python node (temp_id) gets flushed.
    Returns FlushOutcome(SAVED) with a FlushResult carrying temp_id_map.

    Requires transaction=True because flush() calls sync_to_async which
    spawns a thread; without it the graph row is not visible across connections.
    """
    temp_id = "aaaabbbb-0000-0000-0000-000000000001"
    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "python_code": PYTHON_CODE_DATA,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.SAVED
    assert outcome.saved
    assert outcome.safe_to_clear
    result = outcome.result
    assert isinstance(result, FlushResult)
    assert isinstance(result.new_save_version, int)
    assert result.new_save_version > graph.save_version
    assert temp_id in result.temp_id_map
    assert isinstance(result.temp_id_map[temp_id], int)
    assert result.saved_at  # non-empty ISO timestamp


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_happy_path_snapshot_remapped_after_flush(
    graph, base_snapshot, flush_service
):
    """After a successful flush the snapshot has real ids instead of temp_ids
    and the deleted accumulator is cleared."""
    temp_id = "aaaabbbb-0000-0000-0000-000000000002"
    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "python_code": PYTHON_CODE_DATA,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)
    assert outcome.saved
    result = outcome.result

    # Snapshot must be remapped.
    snapshot = await graph_state_service.get_snapshot(graph.id)
    node = snapshot["python_node_list"][0]
    assert node["id"] == result.temp_id_map[temp_id]
    assert "temp_id" not in node

    # deleted accumulator must be cleared (apply_id_remap resets it).
    for ids in snapshot["deleted"].values():
        assert ids == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_idempotency_second_flush_is_all_updates(
    graph, base_snapshot, flush_service
):
    """Flushing twice for the same graph must not create duplicate DB rows.
    After the first flush the snapshot carries real ids; the second flush
    treats everything as updates."""
    temp_id = "aaaabbbb-0000-0000-0000-000000000003"
    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "python_code": PYTHON_CODE_DATA,
                "node_name": "idempotent_node",
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    # First flush — creates the node.
    outcome1 = await flush_service.flush(graph.id)
    assert outcome1.saved
    count_after_first = await count_nodes("python_node_list", graph.id)
    assert count_after_first == 1

    # Second flush — must NOT create a second node.
    outcome2 = await flush_service.flush(graph.id)
    assert outcome2.saved
    count_after_second = await count_nodes("python_node_list", graph.id)
    assert count_after_second == 1

    # The DB node from both flushes must be the same id.
    node = await first_node("python_node_list", graph.id)
    assert node.id == outcome1.result.temp_id_map[temp_id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_validation_failure_returns_none_and_retains_snapshot(
    graph, base_snapshot, flush_service
):
    """A snapshot that fails serializer validation causes flush() to return
    FAILED. The Redis snapshot must be retained so users don't lose work."""
    # Missing both start_node_id/start_temp_id AND end_node_id/end_temp_id —
    # EdgeBulkSerializer fails its cross-field validation.
    snap = base_snapshot(
        save_version=graph.save_version,
        edge_list=[{"start_node_id": None, "end_node_id": None}],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    # Validation failure must return FAILED, not SAVED or NOTHING_TO_FLUSH.
    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.FAILED
    assert not outcome.saved
    assert not outcome.safe_to_clear
    # Snapshot must still be there — do NOT wipe data on failure.
    retained = await graph_state_service.get_snapshot(graph.id)
    assert retained is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nonexistent_graph_clears_snapshot_and_returns_nothing_to_flush(
    base_snapshot, flush_service
):
    """flush() clears the stale snapshot and returns NOTHING_TO_FLUSH when the
    graph pk does not exist in the DB."""
    non_existent_id = 999999
    snap = base_snapshot(save_version=0)
    await graph_state_service.seed(non_existent_id, snap)

    # Confirm snapshot exists before flush.
    assert await graph_state_service.get_snapshot(non_existent_id) is not None

    outcome = await flush_service.flush(non_existent_id)

    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.NOTHING_TO_FLUSH
    assert not outcome.saved
    assert outcome.safe_to_clear

    # Stale snapshot must have been cleared.
    assert await graph_state_service.get_snapshot(non_existent_id) is None


# ---------------------------------------------------------------------------
# FlushOutcome.safe_to_clear semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected_safe_to_clear, expected_saved",
    [
        (FlushStatus.SAVED, True, True),
        (FlushStatus.NOTHING_TO_FLUSH, True, False),
        (FlushStatus.FAILED, False, False),
    ],
)
async def test_flush_outcome_safe_to_clear(
    status, expected_safe_to_clear, expected_saved
):
    """safe_to_clear/saved reflect the outcome status: SAVED and
    NOTHING_TO_FLUSH are safe to clear, FAILED is not (the caller must retain
    the snapshot)."""
    result = None
    if status is FlushStatus.SAVED:
        result = FlushResult(
            new_save_version=2,
            temp_id_map={},
            saved_at="2026-01-01T00:00:00+00:00",
            flushed_deleted={},
        )
    outcome = FlushOutcome(status=status, result=result)
    assert outcome.safe_to_clear is expected_safe_to_clear
    assert outcome.saved is expected_saved


# ---------------------------------------------------------------------------
# Precise deleted-accumulator reconciliation after flush
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_preserves_concurrently_accumulated_deletes(
    graph, base_snapshot, empty_deleted, flush_service
):
    """After a flush, the accumulator entry that was flushed (crew_node id=10,
    which never existed in the DB) is cleared from the snapshot."""
    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[],
        deleted={**empty_deleted(), "crew_node_ids": [10]},
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)
    assert outcome.saved, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert snapshot is not None
    assert 10 not in snapshot["deleted"]["crew_node_ids"]


# ---------------------------------------------------------------------------
# Regression: None entry in node list must not crash the autosave pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_none_entry_in_node_list_does_not_raise(
    monkeypatch, base_snapshot, flush_service
):
    """A None entry (JSON null) in a snapshot node list — e.g. from a corrupted
    Redis write — must not crash flush()'s flushed_temp_id_to_list_key loop
    with AttributeError.

    The None-entry guard in that loop runs before any DB access, so the DB
    call is mocked purely so this test needs no live database — the mocked
    GRAPH_NOT_FOUND result is not what proves the guard works. The
    try/except AttributeError below is the real assertion: if the guard were
    removed, iterating python_node_list would call `.get("temp_id")` on the
    None entry and raise AttributeError before _async_do_db_flush is ever
    called, regardless of what it's mocked to return.
    """
    import tables.graph_collab.flush_service as _fs_module

    corrupted_graph_id = 99998

    async def _fake_db_flush(graph_id, snapshot):
        return _fs_module._DbFlushResult.GRAPH_NOT_FOUND

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _fake_db_flush)

    snap = base_snapshot(
        save_version=0,
        python_node_list=[None],  # the corrupted entry that triggers the bug
    )
    await graph_state_service.seed(corrupted_graph_id, snap)

    try:
        # This is the real assertion — it proves the None-entry guard runs
        # and survives, independent of the mocked DB outcome below.
        outcome = await flush_service.flush(corrupted_graph_id)
    except AttributeError as exc:
        raise AssertionError(
            f"flush() raised AttributeError — the None-entry guard is missing: {exc}"
        ) from exc
    finally:
        await graph_state_service.clear(corrupted_graph_id)

    assert outcome.status is FlushStatus.NOTHING_TO_FLUSH, (
        f"Expected NOTHING_TO_FLUSH (graph not found) but got {outcome.status!r}"
    )


# ---------------------------------------------------------------------------
# flushed_temp_id_to_list_key must include edges/conditional edges, or an
# edge deleted between this flush and the next one can never be resolved to
# its list_key by apply_id_remap's orphan detection — the row would be
# silently orphaned forever.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_builds_temp_id_to_list_key_including_edge_lists(
    monkeypatch, base_snapshot, flush_service
):
    """flush() must include edge_list and conditional_edge_list entries — each
    keyed by the entry's own temp_id — when building flushed_temp_id_to_list_key,
    not just node lists."""
    import tables.graph_collab.flush_service as _fs_module

    graph_id = 99997
    captured: dict = {}

    async def _fake_apply_id_remap(
        graph_id_arg,
        temp_id_map,
        new_save_version,
        *,
        flushed_deleted=None,
        flushed_temp_id_to_list_key=None,
    ):
        captured["flushed_temp_id_to_list_key"] = flushed_temp_id_to_list_key

    async def _fake_db_flush(graph_id_arg, snapshot):
        return 1, {"tmp-edge": 111, "tmp-cond-edge": 222, "tmp-py": 333}

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _fake_db_flush)
    monkeypatch.setattr(
        _fs_module.graph_state_service, "apply_id_remap", _fake_apply_id_remap
    )

    snap = base_snapshot(
        save_version=0,
        python_node_list=[{"temp_id": "tmp-py", "graph": graph_id}],
        edge_list=[{"temp_id": "tmp-edge", "start_node_id": 1, "end_node_id": 2}],
        conditional_edge_list=[{"temp_id": "tmp-cond-edge", "source_node_id": 1}],
    )
    await graph_state_service.seed(graph_id, snap)

    try:
        outcome = await flush_service.flush(graph_id)
    finally:
        await graph_state_service.clear(graph_id)

    assert outcome.status is FlushStatus.SAVED
    list_key_map = captured["flushed_temp_id_to_list_key"]
    assert list_key_map["tmp-py"] == "python_node_list"
    assert list_key_map["tmp-edge"] == "edge_list"
    assert list_key_map["tmp-cond-edge"] == "conditional_edge_list"
