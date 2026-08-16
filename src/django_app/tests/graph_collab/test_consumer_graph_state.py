"""Socket-level tests for graph_state snapshot seeding on connect, mutation via
relayed ops, and clearing on last disconnect."""

import pytest

from tables.graph_collab.graph_state_service import graph_state_service

from tests.graph_collab.conftest import (
    _make_communicator,
    _drain_connect,
    wait_for,
    editor_payload,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_first_connector_receives_graph_state_from_db(test_graph, test_user):
    """First connector must receive graph_state seeded from DB (not request_state)."""
    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()

    await communicator.receive_json_from()  # presence_state

    msg = await communicator.receive_json_from()
    assert msg["type"] == "graph_state", (
        "Server must seed from DB and send graph_state on first connect; "
        f"got {msg['type']!r} instead"
    )
    # The snapshot must contain the canonical superset keys.
    assert "save_version" in msg["flow"]
    assert "crew_node_list" in msg["flow"]
    assert "edge_list" in msg["flow"]
    assert "deleted" in msg["flow"]

    await communicator.receive_json_from()  # user_joined
    await communicator.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_second_connector_receives_same_graph_state_snapshot(
    test_graph, test_user, second_user
):
    """Second connector must receive graph_state carrying the live snapshot seeded from DB."""
    comm1 = _make_communicator(test_graph.pk, test_user)
    await comm1.connect()
    await comm1.receive_json_from()  # presence_state
    # Capture the graph_state message comm1 receives (seeded from DB).
    graph_state_msg = await comm1.receive_json_from()
    assert graph_state_msg["type"] == "graph_state"
    db_snapshot = graph_state_msg["flow"]
    await comm1.receive_json_from()  # user_joined

    comm2 = _make_communicator(test_graph.pk, second_user)
    await comm2.connect()
    await comm1.receive_json_from()  # user_joined for second_user

    await comm2.receive_json_from()  # presence_state

    msg = await comm2.receive_json_from()
    assert msg["type"] == "graph_state"
    # The second connector must receive the same DB-seeded snapshot as the first.
    assert msg["flow"] == db_snapshot

    await comm2.receive_json_from()  # user_joined
    await comm1.disconnect()
    await comm2.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_node_created_op_mutates_snapshot(test_graph, test_user):
    """node_created op must be reflected in the stored snapshot."""
    comm = _make_communicator(test_graph.pk, test_user)
    await comm.connect()
    await _drain_connect(comm)

    # The snapshot is already seeded from DB by connect; send a node_created op.
    await comm.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "tmp-1", "type": "python"},
            "list_key": "python_node_list",
            "editor": editor_payload(test_user),
        }
    )

    async def _node_appears():
        snap = await graph_state_service.get_snapshot(test_graph.pk)
        if snap is None:
            return False
        return any(n.get("temp_id") == "tmp-1" for n in snap["python_node_list"])

    assert await wait_for(_node_appears), (
        "Newly created node must appear in python_node_list after node_created op"
    )

    await comm.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_last_disconnect_clears_snapshot(test_graph, test_user):
    """Snapshot must be cleared once the last editor leaves."""
    comm = _make_communicator(test_graph.pk, test_user)
    await comm.connect()
    await _drain_connect(comm)

    assert await graph_state_service.get_snapshot(test_graph.pk) is not None

    await comm.disconnect()

    async def _snapshot_cleared():
        return await graph_state_service.get_snapshot(test_graph.pk) is None

    assert await wait_for(_snapshot_cleared)
