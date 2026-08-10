"""
Integration tests for Block 4: last-leave autosave triggers wired into GraphEditConsumer.

Covers:
  B. Last-leave flush on disconnect (success and failure paths).
"""

import asyncio

import fakeredis.aioredis
import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.graph_state_service import graph_state_service

from tests.graph_collab.conftest import _drain_connect, _make_communicator


# ---------------------------------------------------------------------------
# Snapshot helpers
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
    }


def _base_snapshot(**overrides) -> dict:
    base = {
        "save_version": 0,
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


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


# ---------------------------------------------------------------------------
# Shared fakeredis fixture for cursor + autosave Redis operations.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


@sync_to_async
def _count_python_nodes(graph_id: int) -> int:
    from tables.models.graph_models import PythonNode

    return PythonNode.objects.filter(graph_id=graph_id).count()


@sync_to_async
def _get_graph_save_version(graph_id: int) -> int:
    from tables.models import Graph

    return Graph.objects.get(pk=graph_id).save_version


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Trigger B: Last-leave flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_last_leave_flush_persists_and_clears_snapshot(
    test_graph, test_user, monkeypatch
):
    """Last editor disconnecting must flush to DB, broadcast graph_saved, then clear snapshot."""

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "aaaabbbb-0000-0000-0000-ccc000000001"
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    initial_version = await _get_graph_save_version(test_graph.pk)

    await communicator.disconnect()

    async def _snapshot_gone():
        return await graph_state_service.get_snapshot(test_graph.pk) is None

    assert await _wait_for(_snapshot_gone, timeout=2.0), (
        "Snapshot was not cleared after last editor left"
    )

    final_version = await _get_graph_save_version(test_graph.pk)
    assert final_version > initial_version, (
        f"save_version did not increment: still {final_version}"
    )

    count = await _count_python_nodes(test_graph.pk)
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
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    async def _failing_flush(graph_id: int):
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


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_last_leave_flush_success_clears_snapshot(
    test_graph, test_user, monkeypatch
):
    """On a SUCCESSFUL last-leave flush the snapshot IS cleared (normal path)."""

    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    temp_id = "aaaabbbb-0000-0000-0000-fff000000001"
    await _apply_create_op(communicator, test_graph.pk, test_user, temp_id)

    await communicator.disconnect()

    async def _snapshot_gone():
        return await graph_state_service.get_snapshot(test_graph.pk) is None

    assert await _wait_for(_snapshot_gone, timeout=2.0), (
        "Snapshot was NOT cleared after successful last-leave flush"
    )
