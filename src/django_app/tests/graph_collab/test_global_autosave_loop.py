"""
Integration tests for the global autosave loop (_global_autosave_loop / _autosave_pass).

Covers:
  - Periodic flush of dirty graphs with graph_saved broadcast.
  - Single flush per pass even with multiple connections to the same graph.
  - Skipping clean graphs.
  - Per-graph isolation (one dirty, one clean).
  - Idempotency of ensure_autosave_loop_running().
"""

import asyncio

import fakeredis.aioredis
import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.graph_state_service import graph_state_service

from tests.graph_collab.conftest import _drain_connect, _make_communicator


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_redis_service(fake_redis, monkeypatch):
    from tables.services import redis_service as _rs_module

    monkeypatch.setattr(
        type(_rs_module.RedisService()),
        "async_redis_client",
        property(lambda self: fake_redis),
    )
    yield


@sync_to_async
def _get_graph_save_version(graph_id: int) -> int:
    from tables.models import Graph

    return Graph.objects.get(pk=graph_id).save_version


@sync_to_async
def _count_python_nodes(graph_id: int) -> int:
    from tables.models.graph_models import PythonNode

    return PythonNode.objects.filter(graph_id=graph_id).count()


async def _wait_for(
    condition_coro, timeout: float = 2.0, interval: float = 0.05
) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if await condition_coro():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


async def _apply_create_op(communicator, graph_id: int, user, temp_id: str) -> None:
    await communicator.send_json_to(
        {
            "type": "node_created",
            "node": {
                "temp_id": temp_id,
                "graph": graph_id,
                "python_code": _PYTHON_CODE_DATA,
            },
            "list_key": "python_node_list",
            "editor": {
                "user_id": user.pk,
                "display_name": "x",
                "avatar_url": None,
            },
        }
    )

    async def _node_in_snapshot():
        snap = await graph_state_service.get_snapshot(graph_id)
        if snap is None:
            return False
        return any(
            n.get("temp_id") == temp_id or n.get("id") is not None
            for n in snap["python_node_list"]
        )

    assert await _wait_for(_node_in_snapshot), (
        f"Node {temp_id!r} did not appear in snapshot"
    )


async def _collect_messages(communicator, timeout: float = 1.0) -> list[dict]:
    messages = []
    try:
        while True:
            msg = await asyncio.wait_for(communicator.receive_json_from(), timeout=timeout)
            messages.append(msg)
    except asyncio.TimeoutError:
        pass
    return messages


# ---------------------------------------------------------------------------
# Test 1: Global loop flushes dirty graph and broadcasts graph_saved
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
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    # Patch the interval in the autosave_loop module (where it's imported at module level).
    monkeypatch.setattr(_al, "AUTOSAVE_FLUSH_INTERVAL_SECONDS", 0.05)
    _al._autosave_task = None
    _al.ensure_autosave_loop_running()

    graph_saved_msg = None

    async def _got_saved():
        nonlocal graph_saved_msg
        try:
            msg = await asyncio.wait_for(communicator.receive_json_from(), timeout=0.1)
            if msg["type"] == "graph_saved":
                graph_saved_msg = msg
                return True
        except (asyncio.TimeoutError, Exception):
            pass
        return False

    assert await _wait_for(_got_saved, timeout=3.0, interval=0.1), (
        "Expected a graph_saved message from the global autosave loop"
    )

    assert graph_saved_msg is not None
    assert graph_saved_msg["graph_id"] == test_graph.pk
    assert "new_save_version" in graph_saved_msg
    assert graph_saved_msg["new_save_version"] > 0
    assert temp_id in graph_saved_msg["temp_id_map"]

    count = await _count_python_nodes(test_graph.pk)
    assert count == 1, f"Expected 1 python node in DB, got {count}"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Test 2: One flush per pass for multiple connections to the same graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_global_autosave_loop_one_flush_for_multiple_connections(
    test_graph, test_user, second_user
):
    from tables.graph_collab.autosave_loop import _autosave_pass

    comm_a = _make_communicator(test_graph.pk, test_user)
    comm_b = _make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for second_user
    await _drain_connect(comm_b)

    temp_id = "loop-test-0000-0000-0000-bbb000000001"
    await _apply_create_op(comm_a, test_graph.pk, test_user, temp_id)
    # comm_b receives the relay of the create op
    await comm_b.receive_json_from()

    initial_version = await _get_graph_save_version(test_graph.pk)

    await _autosave_pass()

    final_version = await _get_graph_save_version(test_graph.pk)
    version_increments = final_version - initial_version
    assert version_increments == 1, (
        f"Expected exactly 1 DB save, got {version_increments} version increments"
    )

    # Both consumers should receive the broadcast.
    msgs_a = await _collect_messages(comm_a, timeout=0.5)
    msgs_b = await _collect_messages(comm_b, timeout=0.5)

    saved_a = [m for m in msgs_a if m.get("type") == "graph_saved"]
    saved_b = [m for m in msgs_b if m.get("type") == "graph_saved"]

    assert len(saved_a) == 1, f"comm_a expected 1 graph_saved, got {len(saved_a)}"
    assert len(saved_b) == 1, f"comm_b expected 1 graph_saved, got {len(saved_b)}"

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Test 3: Clean graph skipped
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Test 4: Multiple graphs — only dirty one is flushed
# ---------------------------------------------------------------------------


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
    await _apply_create_op(comm_1, test_graph.pk, test_user, temp_id)

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


# ---------------------------------------------------------------------------
# Test 5: ensure_autosave_loop_running is idempotent
# ---------------------------------------------------------------------------


def test_ensure_autosave_loop_running_is_idempotent():
    import tables.graph_collab.autosave_loop as _al

    # reset_autosave_task autouse fixture already set _autosave_task = None.
    _al.ensure_autosave_loop_running()
    task_first = _al._autosave_task

    _al.ensure_autosave_loop_running()
    task_second = _al._autosave_task

    assert task_first is task_second, (
        "ensure_autosave_loop_running() must return the same task on repeated calls"
    )

    # Clean up the task created by this sync test (no event loop teardown).
    if task_first is not None and not task_first.done():
        task_first.cancel()
    _al._autosave_task = None
