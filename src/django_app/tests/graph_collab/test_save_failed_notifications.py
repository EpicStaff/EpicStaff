"""
Integration tests for save_failed broadcast on persistent flush errors.

Covers:
  - Persistent failures (validation_error) broadcast save_failed to editors.
  - Transient failures (version_conflict) do NOT broadcast save_failed.
  - Transient failures retain the snapshot.
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


async def _drain_messages(communicator, timeout: float = 0.3) -> list[dict]:
    messages = []
    try:
        while True:
            msg = await asyncio.wait_for(communicator.receive_json_from(), timeout=timeout)
            messages.append(msg)
    except asyncio.TimeoutError:
        pass
    return messages


# ---------------------------------------------------------------------------
# Test 1: Persistent failure broadcasts save_failed
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
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    # Force a persistent validation failure.
    async def _persistent_failure(graph_id, snapshot):
        return _DbFlushResult.SKIP, "validation_error"

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _persistent_failure)

    await _autosave_pass()

    messages = await _drain_messages(communicator, timeout=0.5)
    save_failed_msgs = [m for m in messages if m.get("type") == "save_failed"]

    assert len(save_failed_msgs) == 1, (
        f"Expected 1 save_failed message, got {len(save_failed_msgs)}: {save_failed_msgs}"
    )
    assert save_failed_msgs[0]["graph_id"] == test_graph.pk
    assert save_failed_msgs[0]["reason"] == "validation_error"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Test 2: Version conflict (transient) does NOT broadcast save_failed
# ---------------------------------------------------------------------------


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
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    async def _version_conflict(graph_id, snapshot):
        return _DbFlushResult.VERSION_CONFLICT

    monkeypatch.setattr(_fs_module, "_async_do_db_flush", _version_conflict)

    await _autosave_pass()

    messages = await _drain_messages(communicator, timeout=0.3)
    save_failed_msgs = [m for m in messages if m.get("type") == "save_failed"]

    assert save_failed_msgs == [], (
        f"save_failed must NOT be broadcast for transient version_conflict; got: {save_failed_msgs}"
    )

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Test 3: Version conflict retains the snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_version_conflict_retains_snapshot(
    test_graph, test_user, monkeypatch
):
    from tables.graph_collab.autosave_loop import _autosave_pass
    from tables.graph_collab.flush_service import _DbFlushResult
    import tables.graph_collab.flush_service as _fs_module

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "fail-test-0000-0000-0000-ccc000000001"
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

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
