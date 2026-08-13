"""Consumer-level tests for op_rejected nack on the sender's socket
for a partial node_updated op that GraphLiveStateService.apply_op rejects,
with no relay to peers.

Uses the same WebsocketCommunicator + conftest fixtures pattern as
test_lock_consumer.py. The old test_graph_edit_consumer.py is fully commented
out and is not extended here.
"""

import pytest

from tests.graph_collab.conftest import _drain_connect, _make_communicator


def _editor_payload(user) -> dict:
    return {"user_id": user.pk, "display_name": "x", "avatar_url": None}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_rejected_partial_op_nacks_sender_only(
    test_graph, test_user, second_user
):
    comm_a = _make_communicator(test_graph.pk, test_user)
    comm_b = _make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for second_user
    await _drain_connect(comm_b)

    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": {"id": 999999, "node_name": "Ghost"},
            "list_key": "python_node_list",
            "changed_fields": ["node_name"],
            "op_id": "op-rejected-1",
            "editor": _editor_payload(test_user),
        }
    )

    nack = await comm_a.receive_json_from()
    assert nack["type"] == "op_rejected"
    assert nack["op_id"] == "op-rejected-1"
    assert nack["reason"] == "target_not_found"
    assert nack["list_key"] == "python_node_list"

    assert await comm_b.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_valid_partial_op_relays_to_peer_with_changed_fields(
    test_graph, test_user, second_user
):
    comm_a = _make_communicator(test_graph.pk, test_user)
    comm_b = _make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for second_user
    await _drain_connect(comm_b)

    # Create a node first so there is something to merge onto.
    await comm_a.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": _editor_payload(test_user),
        }
    )
    created_relay = await comm_b.receive_json_from()
    assert created_relay["type"] == "node_created"

    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": {"temp_id": "n1", "node_name": "Node A Renamed"},
            "list_key": "python_node_list",
            "changed_fields": ["node_name"],
            "op_id": "op-valid-1",
            "editor": _editor_payload(test_user),
        }
    )

    relayed = await comm_b.receive_json_from()
    assert relayed["type"] == "node_updated"
    assert relayed["changed_fields"] == ["node_name"]
    assert relayed["node"]["node_name"] == "Node A Renamed"

    # Sender must not receive its own relay, and must not receive an op_rejected.
    assert await comm_a.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_empty_changed_fields_returns_invalid_payload_error(
    test_graph, test_user
):
    comm_a = _make_communicator(test_graph.pk, test_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": {"id": 1, "node_name": "X"},
            "list_key": "python_node_list",
            "changed_fields": [],
            "editor": _editor_payload(test_user),
        }
    )

    error = await comm_a.receive_json_from()
    assert error["type"] == "error"
    assert error["code"] == "invalid_payload"

    await comm_a.disconnect()
