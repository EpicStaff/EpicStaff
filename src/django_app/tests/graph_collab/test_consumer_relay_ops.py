"""Consumer `receive_json` dispatch and `_handle_relay` tests: relay of state
ops to peers (full and partial/changed-fields updates, including op_rejected
nacks for rejected partial ops), server-side editor-identity override, group
isolation across graphs, and protocol-level error responses.
"""

import pytest

from tests.graph_collab.conftest import (
    _drain_connect,
    _make_communicator,
    connect_pair,
    editor_payload,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unknown_message_type_returns_error(
    test_graph, test_user, make_communicator
):
    communicator = make_communicator(test_graph.pk, test_user)
    await communicator.connect()

    # Drain presence_state, user_joined, and graph_state (DB-seeded).
    await communicator.receive_json_from()
    await communicator.receive_json_from()
    await communicator.receive_json_from()

    await communicator.send_json_to({"type": "does_not_exist"})
    msg = await communicator.receive_json_from()

    assert msg["type"] == "error"
    assert msg["code"] == "unknown_message_type"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Relay tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_server_overrides_spoofed_editor_identity(
    test_graph, test_user, second_user
):
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    spoofed_editor = {"user_id": 9999, "display_name": "spoof", "avatar_url": None}
    await comm_a.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "type": "python"},
            "list_key": "python_node_list",
            "editor": spoofed_editor,
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_created"
    assert msg["editor"]["user_id"] == test_user.pk, (
        "server must override editor identity"
    )
    assert msg["node"] == {"temp_id": "n1", "type": "python"}
    assert "sender_channel" not in msg

    assert await comm_a.receive_nothing(timeout=0.3), (
        "sender must not receive its own relay"
    )

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_node_updated_relayed_to_peer(test_graph, test_user, second_user):

    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    node_payload = {"id": 2, "type": "agent", "label": "My Agent"}
    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": node_payload,
            "list_key": "code_agent_node_list",
            "editor": editor_payload(test_user),
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_updated"
    assert msg["node"] == node_payload

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_nodes_deleted_relayed_to_peer(test_graph, test_user, second_user):

    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(
        {
            "type": "nodes_deleted",
            "refs": [
                {"list_key": "crew_node_list", "id": 1},
                {"list_key": "crew_node_list", "id": 2},
            ],
            "editor": editor_payload(test_user),
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "nodes_deleted"
    # The server serialises NodesDeletedMessage via model_dump() which includes
    # all fields: temp_id defaults to null in the wire representation.
    assert msg["refs"] == [
        {
            "list_key": "crew_node_list",
            "id": 1,
            "temp_id": None,
        },
        {
            "list_key": "crew_node_list",
            "id": 2,
            "temp_id": None,
        },
    ]

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_connection_created_relayed_to_peer(test_graph, test_user, second_user):

    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    connection_payload = {"temp_id": "temp-con", "start_node_id": 10, "end_node_id": 11}
    await comm_a.send_json_to(
        {
            "type": "connection_created",
            "connection": connection_payload,
            "list_key": "edge_list",
            "editor": editor_payload(test_user),
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "connection_created"
    assert msg["connection"] == connection_payload

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_group_isolation_across_graphs(
    test_graph, second_graph, test_user, second_user
):
    comm_a = _make_communicator(test_graph.pk, test_user)
    comm_b = _make_communicator(second_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await _drain_connect(comm_b)

    await comm_a.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "type": "python"},
            "list_key": "python_node_list",
            "editor": editor_payload(test_user),
        }
    )

    assert await comm_b.receive_nothing(timeout=0.3), (
        "message sent to graph A must not reach a consumer on graph B"
    )

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_malformed_payload_returns_invalid_payload_error(test_graph, test_user):
    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    # Send node_created without the required `node` field.
    await communicator.send_json_to(
        {
            "type": "node_created",
            "list_key": "crew_node_list",
            "editor": editor_payload(test_user),
        }
    )

    msg = await communicator.receive_json_from()
    assert msg["type"] == "error"
    assert msg["code"] == "invalid_payload"

    # Connection must survive a validation error — send an unknown type next.
    await communicator.send_json_to({"type": "totally_unknown"})
    msg = await communicator.receive_json_from()
    assert msg["type"] == "error"
    assert msg["code"] == "unknown_message_type"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# op_rejected nack on the sender's socket for a partial node_updated op that
# GraphLiveStateService.apply_op rejects, with no relay to peers.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_rejected_partial_op_nacks_sender_only(
    test_graph, test_user, second_user
):
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": {"id": 999999, "node_name": "Ghost"},
            "list_key": "python_node_list",
            "changed_fields": ["node_name"],
            "op_id": "op-rejected-1",
            "editor": editor_payload(test_user),
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
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # Create a node first so there is something to merge onto.
    await comm_a.send_json_to(
        {
            "type": "node_created",
            "node": {"temp_id": "n1", "node_name": "Node A"},
            "list_key": "python_node_list",
            "editor": editor_payload(test_user),
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
            "editor": editor_payload(test_user),
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
            "editor": editor_payload(test_user),
        }
    )

    error = await comm_a.receive_json_from()
    assert error["type"] == "error"
    assert error["code"] == "invalid_payload"

    await comm_a.disconnect()
