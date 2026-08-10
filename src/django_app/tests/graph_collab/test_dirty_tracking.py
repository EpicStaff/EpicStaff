"""Unit tests for dirty-tracking (revision counters) in GraphLiveStateService."""

import pytest
import fakeredis.aioredis

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab.graph_state_service import GraphLiveStateService
from tables.graph_collab.flush_service import FlushStatus, FlushOutcome


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def service(fake_redis, monkeypatch):
    svc = GraphLiveStateService()
    monkeypatch.setattr(type(svc), "_redis", property(lambda self: fake_redis))
    return svc


def _base_snapshot(graph_id: int = 1) -> dict:
    return {
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
        "deleted": {
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
        },
    }


def _node_created_msg():
    from tables.graph_collab.protocol import NodeCreatedMessage

    return NodeCreatedMessage(
        node={
            "temp_id": "abc-123",
            "graph": 1,
            "python_code": {
                "code": "def main(): pass",
                "entrypoint": "main",
                "libraries": [],
            },
        },
        list_key="python_node_list",
        editor={"user_id": 1, "display_name": "Test", "avatar_url": None},
    )


@pytest.mark.asyncio
async def test_revision_bumps_on_apply_op(service):
    graph_id = 1
    await service.seed(graph_id, _base_snapshot(graph_id))
    service._revision[graph_id] = 0
    service._flushed_revision[graph_id] = 0

    assert service.current_revision(graph_id) == 0
    assert not service.is_dirty(graph_id)

    await service.apply_op(graph_id, _node_created_msg())

    assert service.current_revision(graph_id) == 1
    assert service.is_dirty(graph_id)


@pytest.mark.asyncio
async def test_flush_if_dirty_skips_when_clean(service, monkeypatch):
    from tables.graph_collab.flush_service import GraphFlushService

    graph_id = 2
    await service.seed(graph_id, _base_snapshot(graph_id))
    service._revision[graph_id] = 0
    service._flushed_revision[graph_id] = 0

    # Point flush_service internals at our isolated service instance.
    monkeypatch.setattr(
        "tables.graph_collab.flush_service.graph_state_service", service
    )

    flush_called = []
    flush_svc = GraphFlushService()

    original_flush = flush_svc.flush

    async def _spy_flush(gid):
        flush_called.append(gid)
        return await original_flush(gid)

    monkeypatch.setattr(flush_svc, "flush", _spy_flush)

    outcome = await flush_svc.flush_if_dirty(graph_id)

    assert outcome.status is FlushStatus.NOTHING_TO_FLUSH
    assert flush_called == [], "flush() must not be called when snapshot is clean"


@pytest.mark.asyncio
async def test_fix2_race_mark_flushed_captured_revision(service):
    """mark_flushed with a captured revision leaves is_dirty True when edits arrived during flush."""
    graph_id = 3
    await service.seed(graph_id, _base_snapshot(graph_id))
    service._revision[graph_id] = 0
    service._flushed_revision[graph_id] = 0

    await service.apply_op(graph_id, _node_created_msg())
    assert service.current_revision(graph_id) == 1

    captured = service.current_revision(graph_id)

    # Simulate an edit arriving during the DB flush.
    await service.apply_op(graph_id, _node_created_msg())
    assert service.current_revision(graph_id) == 2

    # Flush completes — mark with the captured (not current) revision.
    service.mark_flushed(graph_id, captured)

    # Still dirty because revision 2 > flushed 1.
    assert service.is_dirty(graph_id)


@pytest.mark.asyncio
async def test_clear_resets_revision_state(service):
    graph_id = 4
    await service.seed(graph_id, _base_snapshot(graph_id))
    service._revision[graph_id] = 0
    service._flushed_revision[graph_id] = 0

    await service.apply_op(graph_id, _node_created_msg())
    assert service.is_dirty(graph_id)

    await service.clear(graph_id)

    # Both revision and flushed_revision keys are removed; defaults are both 0 → not dirty.
    assert not service.is_dirty(graph_id)
    assert graph_id not in service._revision
    assert graph_id not in service._flushed_revision
