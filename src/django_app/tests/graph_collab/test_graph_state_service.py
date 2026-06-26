"""
Unit tests for GraphLiveStateService.

Redis is replaced with fakeredis.aioredis.FakeRedis so the real async
get/set/delete logic runs without a live server.
"""

import pytest

from tables.graph_collab import graph_state_service as _gss_module
from tables.graph_collab.protocol import (
    ConnectionCreatedMessage,
    ConnectionDeletedMessage,
    ConnectionWaypointsUpdatedMessage,
    ConnectionsDeletedMessage,
    EditorInfo,
    EntryDeleteRef,
    NodeCreatedMessage,
    NodeUpdatedMessage,
    NodesDeletedMessage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """Override conftest service fixture: return GraphLiveStateService for these tests."""
    return _gss_module.GraphLiveStateService()


def _editor() -> EditorInfo:
    return EditorInfo(user_id=1, display_name="Test", avatar_url=None)


def _flow(crew_node_list=None, edge_list=None) -> dict:
    """Return a minimal superset-snapshot dict.

    The service stores snapshots in superset/Django serializer form, keyed by
    <type>_node_list / edge_list / conditional_edge_list. Tests must use these
    same keys so apply_op can locate and mutate the right lists.
    """
    return {
        "crew_node_list": crew_node_list or [],
        "edge_list": edge_list or [],
        "conditional_edge_list": [],
    }


# ---------------------------------------------------------------------------
# seed / get_snapshot / clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_and_get_round_trip(service):
    flow = _flow(crew_node_list=[{"id": "n1", "type": "agent"}])
    await service.seed(1, flow)
    result = await service.get_snapshot(1)
    assert result == flow


@pytest.mark.asyncio
async def test_get_snapshot_absent_returns_none(service):
    result = await service.get_snapshot(999)
    assert result is None


@pytest.mark.asyncio
async def test_clear_removes_snapshot(service):
    await service.seed(2, _flow())
    await service.clear(2)
    assert await service.get_snapshot(2) is None


# ---------------------------------------------------------------------------
# apply_op — node ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_node_created_adds_node(service):
    await service.seed(1, _flow())
    msg = NodeCreatedMessage(
        node={"id": "n1", "type": "agent"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["crew_node_list"] == [{"id": "n1", "type": "agent"}]


@pytest.mark.asyncio
async def test_apply_node_updated_replaces_node(service):
    await service.seed(
        1, _flow(crew_node_list=[{"id": "n1", "type": "agent", "label": "old"}])
    )
    msg = NodeUpdatedMessage(
        node={"id": "n1", "type": "agent", "label": "new"},
        list_key="crew_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["crew_node_list"]) == 1
    assert snapshot["crew_node_list"][0]["label"] == "new"


@pytest.mark.asyncio
async def test_apply_node_updated_upserts_when_absent(service):
    await service.seed(1, _flow())
    msg = NodeUpdatedMessage(
        node={"id": "n99", "type": "code"},
        list_key="python_node_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["python_node_list"]) == 1
    assert snapshot["python_node_list"][0]["id"] == "n99"


@pytest.mark.asyncio
async def test_apply_nodes_deleted_removes_nodes(service):
    # _match_entry matches integer ids against integer ids. Use integer node ids.
    initial_nodes = [{"id": 10}, {"id": 20}, {"id": 30}]
    await service.seed(1, _flow(crew_node_list=initial_nodes))
    msg = NodesDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="crew_node_list", id=10),
            EntryDeleteRef(list_key="crew_node_list", id=30),
        ],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["crew_node_list"] == [{"id": 20}]


@pytest.mark.asyncio
async def test_apply_nodes_deleted_does_not_touch_connections(service):
    edges = [{"id": 1, "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(crew_node_list=[{"id": 100}], edge_list=edges))
    msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="crew_node_list", id=100)],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    # Connections must be untouched — FE sends connection deletions separately.
    assert snapshot["edge_list"] == edges


# ---------------------------------------------------------------------------
# apply_op — connection ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_connection_created_adds_connection(service):
    await service.seed(1, _flow())
    msg = ConnectionCreatedMessage(
        connection={"id": "c1", "source": "n1", "target": "n2"},
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": "c1", "source": "n1", "target": "n2"}]


@pytest.mark.asyncio
async def test_apply_connection_created_upserts_existing(service):
    existing = [{"id": "c1", "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(edge_list=existing))
    msg = ConnectionCreatedMessage(
        connection={"id": "c1", "source": "n1", "target": "n3"},
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert len(snapshot["edge_list"]) == 1
    assert snapshot["edge_list"][0]["target"] == "n3"


@pytest.mark.asyncio
async def test_apply_connection_deleted_removes_connection(service):
    connections = [{"id": 1}, {"id": 2}]
    await service.seed(1, _flow(edge_list=connections))
    msg = ConnectionDeletedMessage(
        connection_id=1,
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2}]


@pytest.mark.asyncio
async def test_apply_connections_deleted_removes_batch(service):
    connections = [{"id": 1}, {"id": 2}, {"id": 3}]
    await service.seed(1, _flow(edge_list=connections))
    msg = ConnectionsDeletedMessage(
        refs=[
            EntryDeleteRef(list_key="edge_list", id=1),
            EntryDeleteRef(list_key="edge_list", id=3),
        ],
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"] == [{"id": 2}]


@pytest.mark.asyncio
async def test_apply_connection_waypoints_updated_sets_waypoints(service):
    connections = [{"id": 1, "source": "n1", "target": "n2"}]
    await service.seed(1, _flow(edge_list=connections))
    waypoints = [{"x": 10, "y": 20}, {"x": 30, "y": 40}]
    msg = ConnectionWaypointsUpdatedMessage(
        connection_id=1,
        waypoints=waypoints,
        list_key="edge_list",
        editor=_editor(),
    )
    await service.apply_op(1, msg)
    snapshot = await service.get_snapshot(1)
    assert snapshot["edge_list"][0]["waypoints"] == waypoints


# ---------------------------------------------------------------------------
# apply_op — safe no-op on absent snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_op_on_absent_snapshot_is_safe_noop(service):
    msg = NodeCreatedMessage(
        node={"id": "n1"}, list_key="crew_node_list", editor=_editor()
    )
    # Must not raise and must not create a snapshot.
    await service.apply_op(999, msg)
    assert await service.get_snapshot(999) is None
