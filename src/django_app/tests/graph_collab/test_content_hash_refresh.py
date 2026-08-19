"""Regression tests: a stale content_hash left in the Redis live snapshot
after a successful flush must not cause a false ContentHashConflictError on
the next flush. Covers GraphLiveStateService.apply_id_remap's
_refresh_flushed_content_hashes step.
"""

import datetime

import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.flush_service import FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.protocol import NodeCreatedMessage, NodeUpdatedMessage

from tests.graph_collab.conftest import get_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@sync_to_async
def _create_python_node(graph, code: str = "def main(): return 0"):
    from tables.models.graph_models import PythonNode
    from tables.models.python_models import PythonCode

    python_code = PythonCode.objects.create(
        code=code,
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    node = PythonNode.objects.create(
        graph=graph,
        python_code=python_code,
        node_name="Python-Node #1",
        test_input={},
        use_storage=False,
        stream_config={},
        input_map={},
    )
    return node


@sync_to_async
def _python_node_content_hashes(node_id: int) -> tuple[str, str]:
    """Return (node.content_hash, node.python_code.content_hash) — computed
    synchronously since generate_hash() touches FK fields (graph, python_code)."""
    from tables.models.graph_models import PythonNode

    node = PythonNode.objects.select_related("python_code", "graph").get(pk=node_id)
    return node.content_hash, node.python_code.content_hash


@sync_to_async
def _create_schedule_trigger_node(graph):
    from tables.models.graph_models import ScheduleTriggerNode

    # unit=weeks keeps weekdays meaningful (weekdays is only valid with
    # unit="days"/"weeks" per ScheduleTriggerValidator._validate_weekdays);
    # start_date_time + end_type are required for is_active=True per
    # ScheduleTriggerValidator._validate_active_state.
    return ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="schedule-1",
        is_active=True,
        timezone="America/New_York",
        run_mode=ScheduleTriggerNode.RunMode.REPEAT,
        start_date_time=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        every=5,
        unit=ScheduleTriggerNode.TimeUnit.WEEKS,
        weekdays=["mon", "wed"],
        end_type=ScheduleTriggerNode.EndType.NEVER,
    )


# ---------------------------------------------------------------------------
# End-to-end regression: solo editor, two flushes in a row, zero concurrency.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_flush_after_solo_edit_succeeds_for_schedule_trigger_node(
    graph, flush_service
):
    """A solo editor with no concurrent edits must be able to flush the same
    graph twice in a row without a false ContentHashConflictError."""
    await _create_schedule_trigger_node(graph)

    seeded = await graph_state_service.seed_from_db(graph.id)
    assert seeded is True

    first = await flush_service.flush(graph.id)
    assert first.status is FlushStatus.SAVED, (
        f"First flush unexpectedly failed: {first.failure_reason!r}"
    )

    second = await flush_service.flush(graph.id)
    assert second.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {second.status!r} "
        f"(failure_reason={second.failure_reason!r}). apply_id_remap must "
        "refresh content_hash after every flush."
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_third_flush_still_succeeds_after_two_prior_flushes(graph, flush_service):
    """Guards against an off-by-one refresh (e.g. only fixing the FIRST stale
    flush but not keeping subsequent ones in sync)."""
    await _create_python_node(graph)
    await graph_state_service.seed_from_db(graph.id)

    for attempt in range(3):
        outcome = await flush_service.flush(graph.id)
        assert outcome.status is FlushStatus.SAVED, (
            f"Flush #{attempt + 1} failed: {outcome.failure_reason!r}"
        )


# ---------------------------------------------------------------------------
# White-box: apply_id_remap actually overwrites a stale content_hash.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_id_remap_refreshes_stale_schedule_trigger_content_hash(
    graph, base_snapshot, empty_deleted
):
    """A deliberately stale content_hash on a persisted entry must be
    overwritten with the real, freshly-computed value — and the node's
    substantive config must survive the remap untouched."""
    seed_node = await _create_schedule_trigger_node(graph)
    persisted_node = await get_node("schedule_trigger_node_list", seed_node.id)
    real_hash = persisted_node.content_hash

    stale_snapshot = base_snapshot(
        save_version=graph.save_version,
        schedule_trigger_node_list=[
            {
                "id": seed_node.id,
                "graph": graph.id,
                "node_name": "schedule-1",
                "is_active": True,
                "timezone": "America/New_York",
                "run_mode": "repeat",
                "start_date_time": "2026-01-01T00:00:00Z",
                "every": 5,
                "unit": "weeks",
                "weekdays": ["mon", "wed"],
                "end_type": "never",
                "metadata": {},
                "content_hash": "stale-schedule-hash",
                "current_runs": 0,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    )
    await graph_state_service.seed(graph.id, stale_snapshot)

    await graph_state_service.apply_id_remap(
        graph.id,
        {},
        new_save_version=graph.save_version + 1,
        flushed_deleted=empty_deleted(),
    )

    result = await graph_state_service.get_snapshot(graph.id)
    entry = result["schedule_trigger_node_list"][0]
    assert entry["content_hash"] == real_hash

    # The refresh step must only touch content_hash — every other field the
    # node carried before the remap must survive intact.
    assert entry["is_active"] == persisted_node.is_active
    assert entry["timezone"] == persisted_node.timezone
    assert entry["run_mode"] == persisted_node.run_mode
    assert entry["every"] == persisted_node.every
    assert entry["unit"] == persisted_node.unit
    assert entry["weekdays"] == persisted_node.weekdays
    assert entry["end_type"] == persisted_node.end_type


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_id_remap_does_not_fabricate_content_hash_for_new_entry(
    graph, base_snapshot, empty_deleted
):
    """A brand-new entry (temp_id only, not yet persisted) must not get a
    fabricated content_hash — refresh only applies to entries with a real id
    that were actually just persisted."""
    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {"temp_id": "tmp-new", "node_name": "not yet saved"},
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    # No temp_id_map entry for "tmp-new" — simulates a node that is still
    # pending creation (this flush did not touch it).
    await graph_state_service.apply_id_remap(
        graph.id,
        {},
        new_save_version=graph.save_version + 1,
        flushed_deleted=empty_deleted(),
    )

    result = await graph_state_service.get_snapshot(graph.id)
    entry = result["python_node_list"][0]
    assert "content_hash" not in entry
    assert entry.get("temp_id") == "tmp-new"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_apply_id_remap_refreshes_newly_created_node_content_hash(
    graph, base_snapshot, empty_deleted
):
    """A node that WAS just created this flush (temp_id resolved via
    temp_id_map) must get its content_hash populated from the fresh DB row —
    the id-remap and content_hash-refresh steps must compose correctly."""
    node = await _create_python_node(graph)
    real_hash, real_python_code_hash = await _python_node_content_hashes(node.id)

    # Snapshot still carries the temp_id (as it would immediately after the
    # DB write that assigned real id=node.id but before this remap call).
    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {
                "temp_id": "tmp-py-new",
                "node_name": "Python-Node #1",
                "python_code": {
                    "code": "def main(): return 0",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": None,
                },
                "test_input": {},
                "use_storage": False,
                "stream_config": {},
                "input_map": {},
                "output_variable_path": None,
                "metadata": {},
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    await graph_state_service.apply_id_remap(
        graph.id,
        {"tmp-py-new": node.id},
        new_save_version=graph.save_version + 1,
        flushed_deleted=empty_deleted(),
    )

    result = await graph_state_service.get_snapshot(graph.id)
    entry = result["python_node_list"][0]
    assert entry["id"] == node.id
    assert "temp_id" not in entry
    assert entry["python_code"]["content_hash"] == real_python_code_hash
    # python_node_list is a list key whose serializer (PythonNodeSerializer,
    # via ContentHashWritableMixin) exposes "content_hash" — refresh must ADD
    # the key here even though the seed shape (matching the FE's
    # NodeCreatedMessage payload) never had it, so the node gets
    # optimistic-concurrency protection at its first flush instead of
    # waiting for a reseed.
    assert real_hash is not None
    assert entry["content_hash"] == real_hash


# ---------------------------------------------------------------------------
# End-to-end via the real op + flush pipeline: a node created during a live
# session (no content_hash in its payload) must gain one after its first
# flush, and a further edit/flush on top of it must succeed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_session_created_python_node_gains_content_hash_after_first_flush(
    graph, base_snapshot, flush_service, editor
):
    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    temp_id = "tmp-session-created-py"
    create_msg = NodeCreatedMessage(
        node={
            "temp_id": temp_id,
            "graph": graph.id,
            "python_code": {
                "code": "def main(): return 1",
                "entrypoint": "main",
                "libraries": [],
            },
        },
        list_key="python_node_list",
        editor=editor,
    )
    op_result = await graph_state_service.apply_op(graph.id, create_msg)
    assert op_result.status.value == "applied"

    first_flush = await flush_service.flush(graph.id)
    assert first_flush.status is FlushStatus.SAVED, (
        f"First flush failed: {first_flush.failure_reason!r}"
    )

    snapshot_after_first_flush = await graph_state_service.get_snapshot(graph.id)
    entries = snapshot_after_first_flush["python_node_list"]
    assert len(entries) == 1
    entry = entries[0]
    assert "temp_id" not in entry
    real_node_id = entry["id"]

    real_node_hash, real_python_code_hash = await _python_node_content_hashes(
        real_node_id
    )
    assert entry["content_hash"] == real_node_hash, (
        "A node created during the session must have its content_hash "
        "populated in the live snapshot immediately after its first flush."
    )
    assert entry["python_code"]["content_hash"] == real_python_code_hash

    # Edit on top of the now-hashed entry and flush again — must succeed.
    update_msg = NodeUpdatedMessage(
        node={
            "id": real_node_id,
            "graph": graph.id,
            "content_hash": entry["content_hash"],
            "python_code": {
                "code": "def main(): return 2",
                "entrypoint": "main",
                "libraries": [],
                "content_hash": entry["python_code"]["content_hash"],
            },
        },
        list_key="python_node_list",
        editor=editor,
    )
    await graph_state_service.apply_op(graph.id, update_msg)

    second_flush = await flush_service.flush(graph.id)
    assert second_flush.status is FlushStatus.SAVED, (
        f"Second flush (edit on top of a freshly-hashed session-created node) "
        f"failed: {second_flush.failure_reason!r}"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_refresh_does_not_add_content_hash_for_list_key_serializer_omits(
    graph, base_snapshot, flush_service, editor
):
    """code_agent_node_list's serializer does not expose content_hash — a
    freshly-flushed entry in that list must not gain a content_hash key,
    so the live snapshot's shape keeps matching what a DB reseed produces."""
    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    temp_id = "tmp-session-created-code-agent"
    create_msg = NodeCreatedMessage(
        node={"temp_id": temp_id, "graph": graph.id},
        list_key="code_agent_node_list",
        editor=editor,
    )
    await graph_state_service.apply_op(graph.id, create_msg)

    outcome = await flush_service.flush(graph.id)
    assert outcome.status is FlushStatus.SAVED, (
        f"Flush failed: {outcome.failure_reason!r}"
    )

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entries = snapshot["code_agent_node_list"]
    assert len(entries) == 1
    entry = entries[0]
    assert "temp_id" not in entry
    assert entry["id"] is not None
    assert "content_hash" not in entry, (
        "code_agent_node_list's serializer does not declare content_hash — "
        "the refresh step must not fabricate the key for this list."
    )
