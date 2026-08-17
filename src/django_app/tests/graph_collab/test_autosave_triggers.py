"""
Integration tests for the autosave trigger layer: the periodic global
autosave loop, the last-leave flush triggered by a consumer disconnect, and
the save_failed broadcast emitted when a flush fails persistently.
"""

import asyncio

import pytest

from tables.graph_collab.graph_state_service import graph_state_service

from tests.graph_collab.conftest import (
    _drain_connect,
    _make_communicator,
    apply_create_op,
    collect_messages,
    count_nodes,
    get_graph_save_version,
    wait_for,
)


pytestmark = pytest.mark.usefixtures("patch_redis_service")


# ---------------------------------------------------------------------------
# Trigger: Global autosave loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_flushes_dirty_graph_and_broadcasts(
    test_graph, test_user, monkeypatch
):
    import tables.graph_collab.autosave_loop as _al

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "loop-test-0000-0000-0000-aaa000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    initial_version = await get_graph_save_version(test_graph.pk)

    # Patch the interval in the autosave_loop module (where it's imported at module level).
    monkeypatch.setattr(_al, "AUTOSAVE_FLUSH_INTERVAL_SECONDS", 0.05)
    _al._autosave_task = None
    _al.ensure_autosave_loop_running()

    graph_saved_msg = None

    async def _got_saved():
        """checks if graph_saved message was broadcasted"""
        nonlocal graph_saved_msg
        try:
            msg = await asyncio.wait_for(communicator.receive_json_from(), timeout=0.1)
            if msg["type"] == "graph_saved":
                graph_saved_msg = msg
                return True
        except asyncio.TimeoutError:
            pass
        return False

    assert await wait_for(_got_saved, timeout=3.0, interval=0.1), (
        "Expected a graph_saved message from the global autosave loop"
    )

    assert graph_saved_msg is not None
    assert graph_saved_msg["graph_id"] == test_graph.pk
    # mark_flushed makes the graph clean after its first successful flush, so
    # flush_if_dirty short-circuits to NOTHING_TO_FLUSH on every later pass —
    # this is necessarily the ONE save, proving the version moved by exactly 1
    # rather than merely being positive.
    assert graph_saved_msg["new_save_version"] == initial_version + 1
    assert temp_id in graph_saved_msg["temp_id_map"]

    count = await count_nodes("python_node_list", test_graph.pk)
    assert count == 1, f"Expected 1 python node in DB, got {count}"

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_one_flush_for_multiple_connections(
    test_graph, test_user, second_user
):
    """One dirty graph shared by two connections is flushed exactly once per
    pass, and a following pass over the now-clean graph does not re-save it."""
    from tables.graph_collab.autosave_loop import _autosave_pass

    comm_a = _make_communicator(test_graph.pk, test_user)
    comm_b = _make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for second_user
    await _drain_connect(comm_b)

    temp_id = "loop-test-0000-0000-0000-bbb000000001"
    await apply_create_op(comm_a, test_graph.pk, test_user, temp_id)
    # comm_b receives the relay of the create op
    await comm_b.receive_json_from()

    initial_version = await get_graph_save_version(test_graph.pk)

    # Calling _autosave_pass() directly (rather than starting the timer-driven
    # loop) is deterministic: with the real loop you cannot know how many
    # passes have elapsed by the time you assert, so a version-increment count
    # would be racy.
    await _autosave_pass()

    version_after_first_pass = await get_graph_save_version(test_graph.pk)
    assert version_after_first_pass - initial_version == 1, (
        f"Expected exactly 1 DB save, got "
        f"{version_after_first_pass - initial_version} version increments"
    )

    # A second pass over a graph that was just flushed clean must not re-save it.
    await _autosave_pass()

    final_version = await get_graph_save_version(test_graph.pk)
    version_increments = final_version - initial_version
    assert version_increments == 1, (
        f"Expected exactly 1 DB save across both passes, got {version_increments} "
        "version increments"
    )

    # Both consumers should receive the broadcast — exactly one each, proving
    # the second pass also emitted no second broadcast.
    msgs_a = await collect_messages(comm_a, timeout=0.5)
    msgs_b = await collect_messages(comm_b, timeout=0.5)

    saved_a = [m for m in msgs_a if m.get("type") == "graph_saved"]
    saved_b = [m for m in msgs_b if m.get("type") == "graph_saved"]

    assert len(saved_a) == 1, f"comm_a expected 1 graph_saved, got {len(saved_a)}"
    assert len(saved_b) == 1, f"comm_b expected 1 graph_saved, got {len(saved_b)}"

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_skips_clean_graph(
    test_graph, test_user, monkeypatch
):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab import flush_service as _fs_module

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    # After seed_from_db, revision == flushed_revision == 0 → not dirty.
    assert not graph_state_service.is_dirty(test_graph.pk)

    flush_calls = []
    original_flush = _fs_module.flush_service.flush

    async def _spy_flush(graph_id):
        flush_calls.append(graph_id)
        return await original_flush(graph_id)

    monkeypatch.setattr(_fs_module.flush_service, "flush", _spy_flush)

    await _autosave_pass()

    assert flush_calls == [], (
        f"flush() must not be called for a clean graph; got calls: {flush_calls}"
    )

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_multiple_graphs_independent(
    test_graph, second_graph, test_user, second_user, monkeypatch
):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab import flush_service as _fs_module

    comm_1 = _make_communicator(test_graph.pk, test_user)
    comm_2 = _make_communicator(second_graph.pk, second_user)

    await comm_1.connect()
    await _drain_connect(comm_1)

    await comm_2.connect()
    await _drain_connect(comm_2)

    # Make graph_1 dirty, leave graph_2 clean.
    temp_id = "loop-test-0000-0000-0000-ccc000000001"
    await apply_create_op(comm_1, test_graph.pk, test_user, temp_id)

    assert graph_state_service.is_dirty(test_graph.pk)
    assert not graph_state_service.is_dirty(second_graph.pk)

    flushed_graph_ids = []
    original_flush = _fs_module.flush_service.flush

    async def _spy_flush(graph_id):
        flushed_graph_ids.append(graph_id)
        return await original_flush(graph_id)

    monkeypatch.setattr(_fs_module.flush_service, "flush", _spy_flush)

    await _autosave_pass()

    assert test_graph.pk in flushed_graph_ids, "Dirty graph_1 must be flushed"
    assert second_graph.pk not in flushed_graph_ids, "Clean graph_2 must not be flushed"

    await comm_1.disconnect()
    await comm_2.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_multiple_dirty_graphs_both_flushed(
    test_graph, second_graph, test_user, second_user
):
    """A single autosave pass must flush every dirty graph, not just the first
    one it encounters in `presence_service.active_graph_ids()`."""
    from tables.graph_collab.autosave_loop import _autosave_pass

    comm_1 = _make_communicator(test_graph.pk, test_user)
    comm_2 = _make_communicator(second_graph.pk, second_user)

    await comm_1.connect()
    await _drain_connect(comm_1)

    await comm_2.connect()
    await _drain_connect(comm_2)

    temp_id_1 = "loop-test-0000-0000-0000-ddd000000001"
    temp_id_2 = "loop-test-0000-0000-0000-ddd000000002"
    await apply_create_op(comm_1, test_graph.pk, test_user, temp_id_1)
    await apply_create_op(comm_2, second_graph.pk, second_user, temp_id_2)

    initial_version_1 = await get_graph_save_version(test_graph.pk)
    initial_version_2 = await get_graph_save_version(second_graph.pk)

    await _autosave_pass()

    final_version_1 = await get_graph_save_version(test_graph.pk)
    final_version_2 = await get_graph_save_version(second_graph.pk)
    assert final_version_1 - initial_version_1 == 1, (
        "test_graph was not flushed by the pass"
    )
    assert final_version_2 - initial_version_2 == 1, (
        "second_graph was not flushed by the pass"
    )

    count_1 = await count_nodes("python_node_list", test_graph.pk)
    count_2 = await count_nodes("python_node_list", second_graph.pk)
    assert count_1 == 1, (
        f"Expected 1 python node persisted for test_graph, got {count_1}"
    )
    assert count_2 == 1, (
        f"Expected 1 python node persisted for second_graph, got {count_2}"
    )

    await comm_1.disconnect()
    await comm_2.disconnect()


@pytest.mark.asyncio
async def test_ensure_autosave_loop_running_is_idempotent():
    import tables.graph_collab.autosave_loop as _al

    # reset_autosave_task autouse fixture already set _autosave_task = None.
    _al.ensure_autosave_loop_running()
    task_first = _al._autosave_task

    _al.ensure_autosave_loop_running()
    task_second = _al._autosave_task

    assert task_first is task_second, (
        "ensure_autosave_loop_running() must return the same task on repeated calls"
    )

    task_first.cancel()
    try:
        await task_first
    except asyncio.CancelledError:
        pass
    _al._autosave_task = None


# ---------------------------------------------------------------------------
# Trigger: Last-leave flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_last_leave_flush_persists_and_clears_snapshot(test_graph, test_user):
    """Last editor disconnecting must flush to DB, broadcast graph_saved, then clear snapshot."""

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "aaaabbbb-0000-0000-0000-ccc000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    initial_version = await get_graph_save_version(test_graph.pk)

    await communicator.disconnect()

    async def _snapshot_gone():
        return await graph_state_service.get_snapshot(test_graph.pk) is None

    assert await wait_for(_snapshot_gone, timeout=2.0), (
        "Snapshot was not cleared after last editor left"
    )

    final_version = await get_graph_save_version(test_graph.pk)
    assert final_version > initial_version, (
        f"save_version did not increment: still {final_version}"
    )

    count = await count_nodes("python_node_list", test_graph.pk)
    assert count == 1, (
        f"Expected 1 python node in DB after last-leave flush, got {count}"
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_last_leave_flush_failure_retains_snapshot(
    test_graph, test_user, monkeypatch
):
    """If the final flush FAILS, the snapshot must NOT be cleared — unsaved edits must survive."""

    from tables.graph_collab.flush_service import FlushOutcome, FlushStatus

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "aaaabbbb-0000-0000-0000-eee000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    async def _failing_flush(_graph_id: int):
        return FlushOutcome(status=FlushStatus.FAILED)

    import tables.graph_collab.consumers as _cm

    monkeypatch.setattr(_cm.flush_service, "flush", _failing_flush)

    snap_before = await graph_state_service.get_snapshot(test_graph.pk)
    assert snap_before is not None, "Snapshot should exist before last-leave"

    await communicator.disconnect()

    await asyncio.sleep(0.1)

    snap_after = await graph_state_service.get_snapshot(test_graph.pk)
    assert snap_after is not None, (
        "Snapshot was cleared despite flush FAILURE — unsaved edits were lost!"
    )

    nodes = snap_after.get("python_node_list", [])
    assert any(n.get("temp_id") == temp_id for n in nodes), (
        "Snapshot retained but no longer contains the unsaved node"
    )


# ---------------------------------------------------------------------------
# Trigger: save_failed broadcast on persistent failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_persistent_failed_broadcasts_save_failed(
    test_graph, test_user, monkeypatch
):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab.flush_service import _DbFlushResult
    import tables.graph_collab.flush_service as _fs_module

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "fail-test-0000-0000-0000-aaa000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    # Force a persistent validation failure.
    async def _persistent_failure(graph_id, snapshot):
        return _DbFlushResult.SKIP, "validation_error"

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _persistent_failure)

    await _autosave_pass()

    messages = await collect_messages(communicator, timeout=0.5)
    save_failed_msgs = [m for m in messages if m.get("type") == "save_failed"]

    assert len(save_failed_msgs) == 1, (
        f"Expected 1 save_failed message, got {len(save_failed_msgs)}: {save_failed_msgs}"
    )
    assert save_failed_msgs[0]["graph_id"] == test_graph.pk
    assert save_failed_msgs[0]["reason"] == "validation_error"

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_version_conflict_does_not_broadcast_save_failed(
    test_graph, test_user, monkeypatch
):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab.flush_service import _DbFlushResult
    import tables.graph_collab.flush_service as _fs_module

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "fail-test-0000-0000-0000-bbb000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    async def _version_conflict(graph_id, snapshot):
        return _DbFlushResult.VERSION_CONFLICT

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _version_conflict)

    await _autosave_pass()

    messages = await collect_messages(communicator, timeout=0.3)
    save_failed_msgs = [m for m in messages if m.get("type") == "save_failed"]

    assert save_failed_msgs == [], (
        f"save_failed must NOT be broadcast for transient version_conflict; got: {save_failed_msgs}"
    )

    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_version_conflict_retains_snapshot(test_graph, test_user, monkeypatch):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab.flush_service import _DbFlushResult
    import tables.graph_collab.flush_service as _fs_module

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "fail-test-0000-0000-0000-ccc000000001"
    await apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    snap_before = await graph_state_service.get_snapshot(test_graph.pk)
    assert snap_before is not None

    async def _version_conflict(graph_id, snapshot):
        return _DbFlushResult.VERSION_CONFLICT

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _version_conflict)

    await _autosave_pass()

    snap_after = await graph_state_service.get_snapshot(test_graph.pk)
    assert snap_after is not None, (
        "Snapshot must be retained after a transient version_conflict"
    )

    nodes = snap_after.get("python_node_list", [])
    assert any(n.get("temp_id") == temp_id for n in nodes), (
        "Unsaved node must still be in the snapshot after a version_conflict"
    )

    await communicator.disconnect()
