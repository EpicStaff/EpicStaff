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

# Used only by these 5 tests, which call _base_snapshot(...) directly and are
# frozen byte-for-byte per explicit instruction — do not touch their bodies,
# names, or docstrings, and do not migrate them to the base_snapshot fixture:
#   test_flush_flat_start_entry_already_rich_shape_is_idempotent
#   test_flush_flat_end_entry_already_rich_shape_is_idempotent
#   test_flush_flat_webhook_trigger_entry_already_rich_shape_is_idempotent
#   test_flush_flat_telegram_trigger_entry_already_rich_shape_is_idempotent
#   test_flush_flat_crew_entry_already_rich_shape_is_idempotent
# Every other test in this file uses the `base_snapshot`/`empty_deleted`
# fixtures from conftest.py instead.
from tests.graph_collab.conftest import _base_snapshot


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


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
                "python_code": _PYTHON_CODE_DATA,
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
                "python_code": _PYTHON_CODE_DATA,
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
                "python_code": _PYTHON_CODE_DATA,
                "node_name": "idempotent_node",
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    # First flush — creates the node.
    outcome1 = await flush_service.flush(graph.id)
    assert outcome1.saved
    count_after_first = await _count_python_nodes(graph.id)
    assert count_after_first == 1

    # Second flush — must NOT create a second node.
    outcome2 = await flush_service.flush(graph.id)
    assert outcome2.saved
    count_after_second = await _count_python_nodes(graph.id)
    assert count_after_second == 1

    # The DB node from both flushes must be the same id.
    node = await _get_first_python_node(graph.id)
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
# Async helpers (sync_to_async wrappers to avoid Django's async ORM limitation)
# ---------------------------------------------------------------------------


from asgiref.sync import sync_to_async  # noqa: E402 — import after test bodies


@sync_to_async
def _count_python_nodes(graph_id: int) -> int:
    from tables.models.graph_models import PythonNode

    return PythonNode.objects.filter(graph_id=graph_id).count()


@sync_to_async
def _get_first_python_node(graph_id: int):
    from tables.models.graph_models import PythonNode

    return PythonNode.objects.filter(graph_id=graph_id).first()


@sync_to_async
def _get_python_code_for_node(node_id: int):
    """Fetch the PythonCode associated with a PythonNode."""
    from tables.models.graph_models import PythonNode

    node = PythonNode.objects.select_related("python_code").get(pk=node_id)
    return node.python_code


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_already_nested_python_entry_is_idempotent(
    graph, base_snapshot, flush_service
):
    """A python node entry that already has a nested python_code dict flushes
    unchanged — normalizing an already-normalized entry must be idempotent."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    nested_payload = {
        "temp_id": "ddddeeee-0000-0000-0000-000000000007",
        "graph": graph.id,
        "node_name": "Seeded-Node",
        "python_code": {
            "code": "def main(): return 'seeded'",
            "entrypoint": "main",
            "libraries": [],
            "global_kwargs": {},
        },
        "test_input": {},
        "use_storage": False,
        "stream_config": {},
        "input_map": {},
        "output_variable_path": None,
    }
    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=nested_payload,
        list_key="python_node_list",
        editor=editor,
    )
    await graph_state_service.apply_op(graph.id, msg)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    python_node_count = await _count_python_nodes(graph.id)
    assert python_node_count == 1

    node = await _get_first_python_node(graph.id)
    python_code = await _get_python_code_for_node(node.id)
    assert python_code.code == "def main(): return 'seeded'"


# ---------------------------------------------------------------------------
# Flat-shape normalization for start, end, webhook_trigger, telegram_trigger,
# crew node types
# ---------------------------------------------------------------------------


# --- start node helpers ---


@sync_to_async
def _create_start_node(graph):
    """Create a StartNode row for the given graph and return it."""
    from tables.models.graph_models import StartNode

    return StartNode.objects.create(
        graph=graph,
        variables={"variables": {"greeting": "hello"}, "persistent": {}},
    )


@sync_to_async
def _get_start_node(node_id: int):
    from tables.models.graph_models import StartNode

    return StartNode.objects.get(pk=node_id)


@sync_to_async
def _count_start_nodes(graph_id: int) -> int:
    from tables.models.graph_models import StartNode

    return StartNode.objects.filter(graph_id=graph_id).count()


# --- end node helpers ---


@sync_to_async
def _create_end_node(graph):
    """Create an EndNode row for the given graph and return it."""
    from tables.models.graph_models import EndNode

    return EndNode.objects.create(
        graph=graph,
        output_map={"context": "variables"},
    )


@sync_to_async
def _get_end_node(node_id: int):
    from tables.models.graph_models import EndNode

    return EndNode.objects.get(pk=node_id)


@sync_to_async
def _count_end_nodes(graph_id: int) -> int:
    from tables.models.graph_models import EndNode

    return EndNode.objects.filter(graph_id=graph_id).count()


# --- webhook_trigger node helpers ---


@sync_to_async
def _count_webhook_trigger_nodes(graph_id: int) -> int:
    from tables.models.graph_models import WebhookTriggerNode

    return WebhookTriggerNode.objects.filter(graph_id=graph_id).count()


# --- telegram_trigger node helpers ---


@sync_to_async
def _count_telegram_trigger_nodes(graph_id: int) -> int:
    from tables.models.graph_models import TelegramTriggerNode

    return TelegramTriggerNode.objects.filter(graph_id=graph_id).count()


# --- crew node helpers ---


@sync_to_async
def _create_crew_and_crew_node(graph):
    """Create a minimal Crew + CrewNode and return (crew_node, crew).

    The crew is created in the same org as ``graph`` — GraphFlushService
    resolves org scope from ``graph.org_id``, so a crew in a different org
    (or with no org) would be rejected by CrewNodeSerializer.validate_crew_id.
    """
    from tables.models.crew_models import Crew
    from tables.models.graph_models import CrewNode

    crew = Crew.objects.create(name="Test Crew", org=graph.org)
    node = CrewNode.objects.create(
        graph=graph,
        node_name="Crew-Node #1",
        crew=crew,
    )
    return node, crew


@sync_to_async
def _count_crew_nodes(graph_id: int) -> int:
    from tables.models.graph_models import CrewNode

    return CrewNode.objects.filter(graph_id=graph_id).count()


# ---------------------------------------------------------------------------
# start_node flush tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_flat_start_entry_already_rich_shape_is_idempotent(graph):
    """A start node entry already in bulk-save shape (variables at top level) passes
    through normalize_op_entry unchanged."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    temp_id = "aaaabbbb-1111-0000-0000-000000000001"
    rich_payload = {
        "temp_id": temp_id,
        "graph": graph.id,
        "variables": {"variables": {"x": 1}, "persistent": {}},
    }
    await graph_state_service.seed(
        graph.id, _base_snapshot(save_version=graph.save_version)
    )

    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=rich_payload, list_key="start_node_list", editor=editor
    )
    await graph_state_service.apply_op(graph.id, msg)

    service = GraphFlushService()
    outcome = await service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Rich-shape start entry was rejected — idempotency broken."
    )
    count = await _count_start_nodes(graph.id)
    assert count == 1


# ---------------------------------------------------------------------------
# end_node flush tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_flat_end_entry_already_rich_shape_is_idempotent(graph):
    """A end node entry already in bulk-save shape (output_map at top level) passes
    through unchanged."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    temp_id = "aaaabbbb-2222-0000-0000-000000000002"
    rich_payload = {
        "temp_id": temp_id,
        "graph": graph.id,
        "output_map": {"result": "final"},
    }
    await graph_state_service.seed(
        graph.id, _base_snapshot(save_version=graph.save_version)
    )

    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(node=rich_payload, list_key="end_node_list", editor=editor)
    await graph_state_service.apply_op(graph.id, msg)

    service = GraphFlushService()
    outcome = await service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Rich-shape end entry was rejected — idempotency broken."
    )
    count = await _count_end_nodes(graph.id)
    assert count == 1


# ---------------------------------------------------------------------------
# webhook_trigger node flush tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_flat_webhook_trigger_entry_already_rich_shape_is_idempotent(graph):
    """An entry already carrying python_code as a nested dict (DB-seed shape) passes through
    normalize_op_entry unchanged — idempotency check."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    temp_id = "aaaabbbb-3333-0000-0000-000000000003"
    rich_payload = {
        "temp_id": temp_id,
        "graph": graph.id,
        "node_name": "Webhook-Seeded",
        # metadata required by WebhookTriggerNodeSerializer (MetadataMixin in explicit field list)
        "metadata": {},
        "python_code": {
            "code": "def main(): return {}",
            "entrypoint": "main",
            "libraries": [],
            "global_kwargs": {},
        },
        "webhook_trigger": None,
    }
    await graph_state_service.seed(
        graph.id, _base_snapshot(save_version=graph.save_version)
    )

    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=rich_payload, list_key="webhook_trigger_node_list", editor=editor
    )
    await graph_state_service.apply_op(graph.id, msg)

    service = GraphFlushService()
    outcome = await service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Rich-shape webhook_trigger entry was rejected — idempotency broken."
    )
    count = await _count_webhook_trigger_nodes(graph.id)
    assert count == 1


# ---------------------------------------------------------------------------
# telegram_trigger node flush tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_flat_telegram_trigger_entry_already_rich_shape_is_idempotent(
    graph,
):
    """An entry already in bulk-save shape (fields at top level) passes through unchanged."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    temp_id = "aaaabbbb-4444-0000-0000-000000000004"
    rich_payload = {
        "temp_id": temp_id,
        "graph": graph.id,
        "node_name": "Telegram-Seeded",
        "telegram_bot_api_key": "key_seeded",
        "webhook_trigger": None,
        "fields": [],
    }
    await graph_state_service.seed(
        graph.id, _base_snapshot(save_version=graph.save_version)
    )

    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=rich_payload, list_key="telegram_trigger_node_list", editor=editor
    )
    await graph_state_service.apply_op(graph.id, msg)

    service = GraphFlushService()
    outcome = await service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Rich-shape telegram_trigger entry was rejected — idempotency broken."
    )
    count = await _count_telegram_trigger_nodes(graph.id)
    assert count == 1


# ---------------------------------------------------------------------------
# crew node flush tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_flat_crew_entry_already_rich_shape_is_idempotent(graph):
    """An entry already carrying crew_id at top level (either from op-normalize or from
    inject_bulk_save_fields) passes through _normalize_crew_entry unchanged — setdefault
    must not overwrite an existing crew_id."""
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    crew_node, crew = await _create_crew_and_crew_node(graph)

    # Already-rich shape: crew_id is at top level (no data.id needed).
    rich_payload = {
        "id": crew_node.id,
        "graph": graph.id,
        "node_name": "Crew-Node #1",
        "crew_id": crew.id,
    }
    await graph_state_service.seed(
        graph.id, _base_snapshot(save_version=graph.save_version)
    )

    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=rich_payload, list_key="crew_node_list", editor=editor
    )
    await graph_state_service.apply_op(graph.id, msg)

    service = GraphFlushService()
    outcome = await service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Rich-shape crew entry was rejected — idempotency broken."
    )
    count = await _count_crew_nodes(graph.id)
    assert count == 1


# ---------------------------------------------------------------------------
# Bug fix: op-created entries (no `graph` FK) must flush successfully
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_op_created_entries_without_graph_field_succeed(
    graph, base_snapshot, flush_service
):
    """WS-op-created snapshot entries omit the ``graph`` FK field (the FE
    payloads never include it) — inject_bulk_save_fields must fill it in for
    both a node entry (python_node_list) and an edge entry (edge_list)."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import Edge, StartNode

    # Pre-create a start node so the edge can reference a real node ID at one
    # end; the other end is a new python node created via temp_id in this flush.
    start_node = await sync_to_async(StartNode.objects.create)(
        graph=graph, variables={}
    )

    temp_end_id = "ccccdddd-0000-0000-0000-000000000099"

    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {"temp_id": temp_end_id, "python_code": _PYTHON_CODE_DATA},
        ],
        edge_list=[
            {"start_node_id": start_node.id, "end_temp_id": temp_end_id},
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "The 'graph' FK was not injected for op-created entries."
    )
    assert outcome.saved

    python_node_count = await _count_python_nodes(graph.id)
    assert python_node_count == 1

    edge_count = await sync_to_async(Edge.objects.filter(graph_id=graph.id).count)()
    assert edge_count == 1

    from tables.models import Graph

    refreshed = await sync_to_async(Graph.objects.get)(pk=graph.id)
    assert refreshed.save_version > graph.save_version


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_seeded_graph_field_not_clobbered(
    test_graph, second_graph, base_snapshot, flush_service
):
    """setdefault must never overwrite a ``graph`` FK already present on a
    DB-seeded entry."""
    snap = base_snapshot(
        save_version=test_graph.save_version,
        python_node_list=[
            {
                "temp_id": "eeeeeeee-0000-0000-0000-000000000001",
                "graph": test_graph.id,  # explicitly set — must not be overwritten
                "python_code": _PYTHON_CODE_DATA,
            }
        ],
    )
    await graph_state_service.seed(test_graph.id, snap)

    outcome = await flush_service.flush(test_graph.id)

    assert outcome.status is FlushStatus.SAVED

    # The node must belong to `test_graph`, not `second_graph`.
    python_node_count = await _count_python_nodes(test_graph.id)
    assert python_node_count == 1

    other_count = await _count_python_nodes(second_graph.id)
    assert other_count == 0


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

    The DB call is mocked to return GRAPH_NOT_FOUND so this runs without a
    live database — the code path under test runs before the DB call.
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


# ---------------------------------------------------------------------------
# Real graph shape: START + PYTHON + EDGE together
# ---------------------------------------------------------------------------


@sync_to_async
def _create_start_python_edge_graph(graph):
    """Create a StartNode, PythonNode (with PythonCode), and an Edge between them.

    Returns (start_node, python_node, edge, python_code).
    """
    from tables.models.graph_models import Edge, StartNode, PythonNode
    from tables.models.python_models import PythonCode

    start_node = StartNode.objects.create(
        graph=graph,
        variables={},
    )
    python_code = PythonCode.objects.create(
        code="def main(inputs): return inputs",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    python_node = PythonNode.objects.create(
        graph=graph,
        node_name="Python-Node #1",
        python_code=python_code,
        test_input={},
        use_storage=False,
        stream_config={},
        input_map={},
    )
    edge = Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=python_node.id,
        metadata={},
    )
    return start_node, python_node, edge, python_code


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_start_node_null_persistent_variables_crashes_with_none_get(
    graph, base_snapshot, flush_service
):
    """A StartNode node_updated op with data.initialState.persistent_variables=null
    must not crash flush() with 'NoneType' object has no attribute 'get' — a JSON
    null persistent_variables must be treated as an empty dict.

    The fix: StartNodeSerializer.validate() must coerce a null persistent_variables
    to {} (or equivalent empty dict) before calling .get() on it, so that a null
    value in the initialState JSON is treated as "no persistent variables configured"
    rather than causing an unhandled AttributeError.
    """
    from tables.graph_collab.protocol import EditorInfo, NodeUpdatedMessage

    start_node, python_node, edge, python_code = await _create_start_python_edge_graph(
        graph
    )

    start_node_hash = await sync_to_async(lambda: start_node.content_hash)()

    # Seed the snapshot with the StartNode in DB-seed shape.
    initial_snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "id": start_node.id,
                "graph": graph.id,
                "variables": {},
                "metadata": {},
                "content_hash": start_node_hash,
            }
        ],
    )
    await graph_state_service.seed(graph.id, initial_snap)

    # A node_updated op for the StartNode where data.initialState contains
    # persistent_variables as null — the key is present but the value is JSON null.
    flat_start_null_persistent_variables = {
        "id": start_node.id,
        "type": "start",
        "node_name": "__start__",
        "nodeNumber": 1,
        "data": {
            "initialState": {
                "variables": {},
                "persistent_variables": None,  # null in JSON — the exact bug trigger
            },
        },
        "position": {"x": 0, "y": 0},
        "ports": [],
        "graph": graph.id,
    }
    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = NodeUpdatedMessage(
        node=flat_start_null_persistent_variables,
        list_key="start_node_list",
        editor=editor,
    )
    await graph_state_service.apply_op(graph.id, msg)

    # Before the fix this raised AttributeError from StartNodeSerializer.validate()
    # (persistent_variables.get(...) on None). After the fix flush() must not raise.
    try:
        outcome = await flush_service.flush(graph.id)
    except AttributeError as exc:
        raise AssertionError(
            f"flush() propagated AttributeError to the caller — it must be caught "
            f"internally and returned as a FAILED outcome: {exc}"
        ) from exc

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Null persistent_variables in initialState should be treated as empty "
        "and the flush should succeed."
    )


# ---------------------------------------------------------------------------
# A brand-new connection carrying a composite-string temp_id (not a UUID) must
# be normalized to a valid UUID before flush.
# ---------------------------------------------------------------------------


# TODO: open design question — composite string temp_ids are no longer hashed
# into UUIDs. apply_op now copies connection_created payloads verbatim
# (graph_state_service._apply_node_upsert / the ConnectionCreatedMessage
# branch), so a composite string temp_id (e.g. "<sourcePortId>+<targetPortId>")
# is never hashed into a UUID before reaching the snapshot, and
# EdgeBulkSerializer.temp_id (a UUIDField) rejects it with "Must be a valid
# UUID." This test is kept (not deleted) per explicit instruction, commented
# out until a replacement normalization strategy is decided.
#
# @pytest.mark.django_db(transaction=True)
# @pytest.mark.asyncio
# async def test_flush_new_edge_with_composite_string_temp_id_succeeds(
#     graph, base_snapshot, flush_service
# ):
#     """A brand-new connection sent via connection_created carries a
#     composite-string temp_id (e.g. "<sourcePortId>+<targetPortId>"), not a
#     UUID. apply_op must normalize it to a valid UUID before it reaches the
#     snapshot, and flush() must succeed."""
#     from asgiref.sync import sync_to_async
#     from tables.graph_collab.protocol import ConnectionCreatedMessage, EditorInfo
#     from tables.models.graph_models import Edge, StartNode, PythonNode
#     from tables.models.python_models import PythonCode
#
#     start_node = await sync_to_async(StartNode.objects.create)(
#         graph=graph, variables={}
#     )
#     python_code = await sync_to_async(PythonCode.objects.create)(
#         code="def main(inputs): return inputs",
#         entrypoint="main",
#         libraries="",
#         global_kwargs={},
#     )
#     python_node = await sync_to_async(PythonNode.objects.create)(
#         graph=graph,
#         node_name="Python-Node #1",
#         python_code=python_code,
#         test_input={},
#         use_storage=False,
#         stream_config={},
#         input_map={},
#     )
#
#     await graph_state_service.seed(
#         graph.id, base_snapshot(save_version=graph.save_version)
#     )
#
#     composite_temp_id = "abc-port-1+def-port-2"
#     connection_payload = {
#         "temp_id": composite_temp_id,
#         "start_node_id": start_node.id,
#         "end_node_id": python_node.id,
#         "metadata": {},
#         "graph": graph.id,
#     }
#     editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
#     msg = ConnectionCreatedMessage(
#         connection=connection_payload,
#         list_key="edge_list",
#         editor=editor,
#     )
#     await graph_state_service.apply_op(graph.id, msg)
#
#     snapshot = await graph_state_service.get_snapshot(graph.id)
#     stored_entry = next(
#         entry
#         for entry in snapshot["edge_list"]
#         if entry.get("start_node_id") == start_node.id
#     )
#     import uuid
#
#     uuid.UUID(stored_entry["temp_id"])  # raises ValueError if not a valid UUID
#     assert stored_entry["temp_id"] != composite_temp_id
#
#     outcome = await flush_service.flush(graph.id)
#
#     assert outcome.status is FlushStatus.SAVED, (
#         f"Expected SAVED but got {outcome.status!r} "
#         f"(failure_reason={outcome.failure_reason!r}). "
#         "A new edge with a composite-string temp_id was not normalized to a "
#         "valid UUID before flush."
#     )
#
#     edge_count = await sync_to_async(Edge.objects.filter(graph_id=graph.id).count)()
#     assert edge_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_op_edge_normalization_is_idempotent_on_real_uuid(
    graph, base_snapshot
):
    """A connection_created op whose temp_id is already a valid UUID is
    unaffected by apply_op — calling it twice (e.g. a duplicate op replay)
    must not produce a different UUID each time."""
    from tables.graph_collab.protocol import ConnectionCreatedMessage, EditorInfo

    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    real_uuid_temp_id = "aaaabbbb-cccc-dddd-eeee-000000000123"
    connection_payload = {
        "temp_id": real_uuid_temp_id,
        "start_node_id": None,
        "end_node_id": None,
        "metadata": {},
        "graph": graph.id,
    }
    editor = EditorInfo(user_id=1, display_name="Test User", avatar_url=None)
    msg = ConnectionCreatedMessage(
        connection=connection_payload,
        list_key="edge_list",
        editor=editor,
    )

    await graph_state_service.apply_op(graph.id, msg)
    await graph_state_service.apply_op(graph.id, msg)

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert len(snapshot["edge_list"]) == 1
    assert snapshot["edge_list"][0]["temp_id"] == real_uuid_temp_id


# ---------------------------------------------------------------------------
# reconcile_against_db self-heals drift from an external CASCADE delete (e.g.
# deleting a Crew cascade-deletes its CrewNode) that leaves the live snapshot
# holding a stale node entry and/or edge refs to it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_prunes_stale_crew_node_and_dangling_edge_after_out_of_band_delete(
    graph, base_snapshot, flush_service
):
    """A CrewNode row removed out-of-band (e.g. its Crew was deleted,
    cascading the CrewNode) while the live snapshot still carries an UPDATE
    entry for that node plus an edge referencing it must be pruned by
    reconcile_against_db rather than wedging autosave forever."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import CrewNode, Edge, StartNode

    crew_node, crew = await _create_crew_and_crew_node(graph)
    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "id": crew_node.id,
                "graph": graph.id,
                "node_name": "Crew-Node #1",
                "crew_id": crew.id,
            }
        ],
        edge_list=[
            {
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    # Simulate the CrewNode row vanishing out-of-band — the live snapshot is
    # not told.
    await sync_to_async(CrewNode.objects.filter(id=crew_node.id).delete)()

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not prune the stale crew node / dangling edge."
    )

    # The stale crew node must not have been recreated.
    assert not await sync_to_async(CrewNode.objects.filter(id=crew_node.id).exists)()

    # The dangling edge (referencing the now-gone crew node) must not exist.
    assert not await sync_to_async(
        Edge.objects.filter(graph_id=graph.id, end_node_id=crew_node.id).exists
    )()

    # The untouched, still-valid start node must survive unaffected.
    assert await sync_to_async(
        StartNode.objects.filter(id=start_node.id, graph_id=graph.id).exists
    )()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_reconcile_leaves_valid_payload_untouched(
    graph, base_snapshot, flush_service
):
    """Sanity check: when every referenced id is still valid in the DB,
    reconcile_against_db must not prune anything."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import CrewNode, Edge

    crew_node, crew = await _create_crew_and_crew_node(graph)
    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "id": crew_node.id,
                "graph": graph.id,
                "node_name": "Crew-Node #1",
                "crew_id": crew.id,
            }
        ],
        edge_list=[
            {
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED
    assert await sync_to_async(CrewNode.objects.filter(id=crew_node.id).exists)()
    assert await sync_to_async(
        Edge.objects.filter(
            graph_id=graph.id, start_node_id=start_node.id, end_node_id=crew_node.id
        ).exists
    )()


# ---------------------------------------------------------------------------
# reconcile_against_db reaps pre-existing orphan edges (real DB rows, not
# just payload refs) and nulls dangling decision-table routing refs, instead
# of merely dropping them from this flush's payload.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_reaps_preexisting_orphan_edge_from_db(
    graph, base_snapshot, flush_service
):
    """An orphan Edge row (its end node already gone from the DB, e.g. via a
    prior crew-cascade delete the live snapshot never learned about) must be
    DELETEd by the flush, not just pruned from this tick's payload — otherwise
    the row survives and reappears on the next seed_from_db."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import CrewNode, Edge

    crew_node, crew = await _create_crew_and_crew_node(graph)
    start_node = await _create_start_node(graph)

    orphan_edge = await sync_to_async(Edge.objects.create)(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=crew_node.id,
        metadata={},
    )

    # The crew node vanishes out-of-band; the live snapshot still carries the
    # now-orphan edge but no longer carries the crew node itself (mirrors a
    # snapshot that was seeded/edited before the out-of-band delete).
    await sync_to_async(CrewNode.objects.filter(id=crew_node.id).delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        edge_list=[
            {
                "id": orphan_edge.id,
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )
    assert not await sync_to_async(Edge.objects.filter(id=orphan_edge.id).exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dangling_decision_table_routing_ref(
    graph, base_snapshot, flush_service
):
    """A DecisionTableNode still routing (default_next_node_id,
    next_error_node_id, condition_groups[].next_node_id) to a node already
    gone from the DB must have those refs nulled by reconcile_against_db, so
    the flush succeeds instead of failing with "routing references node IDs
    that do not exist"."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import (
        ConditionGroup,
        DecisionTableNode,
        EndNode,
    )

    end_node = await _create_end_node(graph)
    decision_table_node = await sync_to_async(DecisionTableNode.objects.create)(
        graph=graph,
        node_name="Decision Table #1",
        default_next_node_id=end_node.id,
        next_error_node_id=end_node.id,
    )
    condition_group = await sync_to_async(ConditionGroup.objects.create)(
        decision_table_node=decision_table_node,
        group_name="group-1",
        group_type="simple",
        order=0,
        next_node_id=end_node.id,
    )

    # The routing target vanishes out-of-band — the live snapshot still
    # carries the decision table routing to it.
    await sync_to_async(EndNode.objects.filter(id=end_node.id).delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        decision_table_node_list=[
            {
                "id": decision_table_node.id,
                "graph": graph.id,
                "node_name": "Decision Table #1",
                "default_next_node_id": end_node.id,
                "next_error_node_id": end_node.id,
                "condition_groups": [
                    {
                        "id": condition_group.id,
                        "group_name": "group-1",
                        "group_type": "simple",
                        "order": 0,
                        "next_node_id": end_node.id,
                    }
                ],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not null the dangling routing ref."
    )

    await sync_to_async(decision_table_node.refresh_from_db)()
    assert decision_table_node.default_next_node_id is None
    assert decision_table_node.next_error_node_id is None

    # DecisionTableNodeSaveable recreates condition_groups wholesale on
    # update (delete-then-recreate, not an in-place update) — the original
    # ConditionGroup row is gone, so assert on the survivor via the FK.
    surviving_group = await sync_to_async(
        lambda: ConditionGroup.objects.get(decision_table_node=decision_table_node)
    )()
    assert surviving_group.next_node_id is None


# ---------------------------------------------------------------------------
# reconcile_against_db collapses a duplicated singleton (start_node_list /
# end_node_list) already stuck in the live snapshot before the op-time dedup
# in apply_op shipped.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_collapses_duplicate_start_node_entries_preferring_real_id(
    graph, base_snapshot, flush_service
):
    """A snapshot corrupted with two start_node_list entries (the persisted
    row plus a stray duplicate create) must be collapsed to one by
    reconcile_against_db, preferring the entry with the real id, and the
    flush must succeed instead of hitting unique_graph_start_node."""
    from asgiref.sync import sync_to_async
    from tables.models.graph_models import StartNode

    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "id": start_node.id,
                "graph": graph.id,
                "variables": {"variables": {"greeting": "hello"}, "persistent": {}},
            },
            {
                # Stray duplicate create — no id, as if a mismatched-temp_id
                # op had appended a second entry before the Bug 5 op-time fix.
                "temp_id": "stray-duplicate",
                "graph": graph.id,
                "variables": {"variables": {}, "persistent": {}},
            },
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not collapse the duplicate start_node_list entries."
    )

    count = await sync_to_async(StartNode.objects.filter(graph_id=graph.id).count)()
    assert count == 1, "Duplicate start node entry was persisted instead of collapsed."

    surviving = await sync_to_async(StartNode.objects.get)(graph_id=graph.id)
    assert surviving.id == start_node.id, (
        "The persisted (real-id) start node entry must survive the collapse."
    )


# ---------------------------------------------------------------------------
# delete-then-create-singleton-in-one-flush deadlock.
#
# GraphBulkSaveService.save() builds its Pass-1 db_map from a live DB query
# (the deletion itself only runs in Pass 2), so a delete-old-End +
# create-new-End in the same flush used to make the singleton guard see the
# still-present old row and reject the create with "Only one end_node_list
# entry allowed per graph" — every autosave tick, forever. Fixed by excluding
# ids pending deletion (``deleted[config.delete_key]``) from Pass-1's db_map.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_delete_and_recreate_end_node_singleton_in_one_flush(
    graph, base_snapshot, empty_deleted, flush_service
):
    """Deleting the persisted End node and creating a new one (temp_id only)
    within the same autosave flush must succeed, leaving exactly one EndNode
    — the new one — instead of deadlocking on the singleton guard."""
    old_end = await _create_end_node(graph)

    new_temp_id = "eeeeffff-0000-0000-0000-000000000001"
    snap = base_snapshot(
        save_version=graph.save_version,
        end_node_list=[
            {
                "temp_id": new_temp_id,
                "graph": graph.id,
                "output_map": {"result": "output"},
            }
        ],
        deleted={**empty_deleted(), "end_node_ids": [old_end.id]},
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "delete-old-End + create-new-End in one flush deadlocked on the "
        "singleton guard."
    )

    count = await _count_end_nodes(graph.id)
    assert count == 1, "Old and new End node both persisted — singleton violated."

    surviving = await _get_end_node(outcome.result.temp_id_map[new_temp_id])
    assert surviving.id != old_end.id, "The old End node row was not replaced."
    assert surviving.output_map == {"result": "output"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_delete_and_recreate_start_node_singleton_in_one_flush(
    graph, base_snapshot, empty_deleted, flush_service
):
    """Same deadlock as above, for StartNode (unique_graph_start_node)."""
    old_start = await _create_start_node(graph)

    new_temp_id = "eeeeffff-0000-0000-0000-000000000002"
    snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "temp_id": new_temp_id,
                "graph": graph.id,
                "variables": {"variables": {"greeting": "new"}, "persistent": {}},
            }
        ],
        deleted={**empty_deleted(), "start_node_ids": [old_start.id]},
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "delete-old-Start + create-new-Start in one flush deadlocked on the "
        "singleton guard."
    )

    count = await _count_start_nodes(graph.id)
    assert count == 1, "Old and new Start node both persisted — singleton violated."

    surviving = await _get_start_node(outcome.result.temp_id_map[new_temp_id])
    assert surviving.id != old_start.id, "The old Start node row was not replaced."
    assert surviving.variables["variables"]["greeting"] == "new"


@pytest.mark.django_db
def test_bulk_save_two_end_node_creates_in_one_payload_still_rejected(graph):
    """Regression: without any deletion in the payload, two temp-only End
    creates in one flush must still be rejected by the singleton guard —
    the deletion-aware db_map must not weaken this check."""
    from tables.exceptions import BulkSaveValidationError
    from tables.serializers.graph_bulk_save_serializers import (
        GraphBulkSaveInputSerializer,
    )
    from tables.services.graph_bulk_save_service import GraphBulkSaveService

    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {
                "temp_id": "aaaa0000-0000-0000-0000-000000000001",
                "graph": graph.id,
                "output_map": {},
            },
            {
                "temp_id": "aaaa0000-0000-0000-0000-000000000002",
                "graph": graph.id,
                "output_map": {},
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    errors = excinfo.value.errors
    assert "end_node_list" in errors
    assert any(
        "Only one end_node_list entry allowed per graph" in str(entry["errors"])
        for entry in errors["end_node_list"]
    )


@pytest.mark.django_db
def test_bulk_save_update_existing_end_node_not_pending_deletion_still_works(graph):
    """Regression: a normal update to an existing End node (real id present in
    end_node_list, absent from deleted) must still resolve against db_map —
    the deletion-aware filter must not accidentally exclude non-deleted ids."""
    from tables.models.graph_models import EndNode
    from tables.services.graph_bulk_save_service import GraphBulkSaveService
    from tables.serializers.graph_bulk_save_serializers import (
        GraphBulkSaveInputSerializer,
    )

    end_node = EndNode.objects.create(graph=graph, output_map={"context": "variables"})

    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {"id": end_node.id, "graph": graph.id, "output_map": {"result": "updated"}},
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    GraphBulkSaveService().save(graph, serializer.validated_data, org_id=graph.org_id)

    assert EndNode.objects.filter(graph=graph).count() == 1
    end_node.refresh_from_db()
    assert end_node.output_map == {"result": "updated"}


@pytest.mark.django_db
def test_bulk_save_end_node_id_in_both_update_list_and_deleted_is_rejected(
    graph, empty_deleted
):
    """Documented edge case: the same real id appears in end_node_list (as an
    update) AND in deleted.end_node_ids in the same payload. The
    deletion-aware db_map excludes it from Pass-1's lookup set, so the
    update branch now reports "not found in graph" instead of silently
    updating a row about to be deleted."""
    from tables.exceptions import BulkSaveValidationError
    from tables.models.graph_models import EndNode
    from tables.serializers.graph_bulk_save_serializers import (
        GraphBulkSaveInputSerializer,
    )
    from tables.services.graph_bulk_save_service import GraphBulkSaveService

    end_node = EndNode.objects.create(graph=graph, output_map={"context": "variables"})

    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {"id": end_node.id, "graph": graph.id, "output_map": {"result": "updated"}},
        ],
        "deleted": {**empty_deleted(), "end_node_ids": [end_node.id]},
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    errors = excinfo.value.errors
    assert "end_node_list" in errors
    assert any(
        f"id={end_node.id} not found in graph {graph.id}" in str(entry["errors"])
        for entry in errors["end_node_list"]
    )
