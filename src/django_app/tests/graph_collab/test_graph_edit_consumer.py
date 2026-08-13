# import pytest

# from tables.graph_collab.graph_state_service import graph_state_service

# from tests.graph_collab.conftest import _make_communicator, _drain_connect


# async def _wait_for(
#     condition_coro, timeout: float = 1.0, interval: float = 0.05
# ) -> bool:
#     """Poll condition_coro() until it returns truthy or timeout is reached."""
#     import asyncio as _asyncio

#     elapsed = 0.0
#     while elapsed < timeout:
#         if await condition_coro():
#             return True
#         await _asyncio.sleep(interval)
#         elapsed += interval
#     return False


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_connect_authenticated_receives_no_error(
#     test_graph, test_user, make_communicator
# ):
#     communicator = make_communicator(test_graph.pk, test_user)
#     connected, _ = await communicator.connect()
#     assert connected
#     await communicator.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_connect_anonymous_is_rejected(test_graph, make_communicator):
#     communicator = make_communicator(test_graph.pk, user=None)
#     connected, code = await communicator.connect()
#     assert not connected
#     assert code == 4401


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_connect_nonexistent_graph_is_rejected(test_user, make_communicator):
#     communicator = make_communicator(999999, test_user)
#     connected, code = await communicator.connect()
#     assert not connected
#     assert code == 4404


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_unknown_message_type_returns_error(
#     test_graph, test_user, make_communicator
# ):
#     communicator = make_communicator(test_graph.pk, test_user)
#     await communicator.connect()

# <<<<<<< Updated upstream
#     # Drain presence_state, user_joined, and graph_state.
# =======
#     # Drain presence_state, user_joined, and graph_state (DB-seeded).
# >>>>>>> Stashed changes
#     await communicator.receive_json_from()
#     await communicator.receive_json_from()
#     await communicator.receive_json_from()

#     await communicator.send_json_to({"type": "does_not_exist"})
#     msg = await communicator.receive_json_from()

#     assert msg["type"] == "error"
#     assert msg["code"] == "unknown_message_type"

#     await communicator.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_graph_saved_pushed_via_notifier(
#     test_graph, test_user, make_communicator
# ):
#     from asgiref.sync import sync_to_async
#     from django.utils import timezone

#     from tables.graph_collab.notifications import GraphEditNotifier

#     communicator = make_communicator(test_graph.pk, test_user)
#     await communicator.connect()

# <<<<<<< Updated upstream
#     # Drain presence_state, user_joined, and graph_state.
# =======
#     # Drain presence_state, user_joined, and graph_state (DB-seeded).
# >>>>>>> Stashed changes
#     await communicator.receive_json_from()
#     await communicator.receive_json_from()
#     await communicator.receive_json_from()

#     await sync_to_async(GraphEditNotifier.notify_graph_saved)(
#         graph_id=test_graph.pk,
#         new_save_version=5,
#         user=test_user,
#         saved_at=timezone.now().isoformat(),
#     )

#     msg = await communicator.receive_json_from()
#     assert msg["type"] == "graph_saved"
#     assert msg["graph_id"] == test_graph.pk
#     assert msg["new_save_version"] == 5
#     assert msg["saved_by"]["user_id"] == test_user.pk

#     await communicator.disconnect()


# # --- Presence tests ---


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_first_user_connect_receives_presence_state_with_self(
#     test_graph, test_user, make_communicator
# ):
#     communicator = make_communicator(test_graph.pk, test_user)
#     await communicator.connect()

#     msg = await communicator.receive_json_from()
#     assert msg["type"] == "presence_state"
#     editors = msg["editors"]
#     assert len(editors) == 1
#     assert editors[0]["user_id"] == test_user.pk

#     await communicator.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_second_user_connect_first_receives_user_joined(
#     test_graph, test_user, second_user, make_communicator
# ):
#     comm1 = make_communicator(test_graph.pk, test_user)
#     comm2 = make_communicator(test_graph.pk, second_user)

#     await comm1.connect()
#     # Drain comm1 initial messages.
#     await comm1.receive_json_from()  # presence_state
# <<<<<<< Updated upstream
#     await comm1.receive_json_from()  # graph_state (seeded from DB on first connect)
# =======
#     await comm1.receive_json_from()  # graph_state (DB-seeded)
# >>>>>>> Stashed changes
#     await comm1.receive_json_from()  # user_joined (self)

#     await comm2.connect()

#     # comm1 should receive user_joined for second_user.
#     msg = await comm1.receive_json_from()
#     assert msg["type"] == "user_joined"
#     assert msg["editor"]["user_id"] == second_user.pk

#     # comm2's presence_state should contain both users.
#     msg = await comm2.receive_json_from()
#     assert msg["type"] == "presence_state"
#     editor_ids = {e["user_id"] for e in msg["editors"]}
#     assert test_user.pk in editor_ids
#     assert second_user.pk in editor_ids

#     await comm1.disconnect()
#     await comm2.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_user_disconnect_remaining_receives_user_left(
#     test_graph, test_user, second_user, make_communicator
# ):
#     comm1 = make_communicator(test_graph.pk, test_user)
#     comm2 = make_communicator(test_graph.pk, second_user)

#     await comm1.connect()
#     await comm1.receive_json_from()  # presence_state
# <<<<<<< Updated upstream
#     await comm1.receive_json_from()  # graph_state (seeded from DB)
# =======
#     await comm1.receive_json_from()  # graph_state (DB-seeded)
# >>>>>>> Stashed changes
#     await comm1.receive_json_from()  # user_joined (self)

#     await comm2.connect()
#     await comm1.receive_json_from()  # user_joined for second_user
#     await comm2.receive_json_from()  # presence_state
# <<<<<<< Updated upstream
#     await (
#         comm2.receive_json_from()
#     )  # graph_state (snapshot already cached by comm1's connect)
# =======
#     await comm2.receive_json_from()  # graph_state (cached from comm1's seed)
# >>>>>>> Stashed changes
#     await comm2.receive_json_from()  # user_joined (self)

#     await comm1.disconnect()

#     # comm2 should receive user_left with test_user's id.
#     msg = await comm2.receive_json_from()
#     assert msg["type"] == "user_left"
#     assert msg["user_id"] == test_user.pk

#     await comm2.disconnect()


# # ---------------------------------------------------------------------------
# # Relay tests
# # ---------------------------------------------------------------------------


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_server_overrides_spoofed_editor_identity(
#     test_graph, test_user, second_user
# ):
#     comm_a = _make_communicator(test_graph.pk, test_user)
#     comm_b = _make_communicator(test_graph.pk, second_user)

#     await comm_a.connect()
#     await _drain_connect(comm_a)

#     await comm_b.connect()
#     await comm_a.receive_json_from()  # user_joined for second_user
#     await _drain_connect(comm_b)

#     spoofed_editor = {"user_id": 9999, "display_name": "spoof", "avatar_url": None}
#     await comm_a.send_json_to(
#         {
#             "type": "node_created",
# <<<<<<< Updated upstream
#             "node": {"id": "n1", "type": "python"},
# =======
#             "node": {"id": 1, "type": "python"},
# >>>>>>> Stashed changes
#             "list_key": "python_node_list",
#             "editor": spoofed_editor,
#         }
#     )

#     msg = await comm_b.receive_json_from()
#     assert msg["type"] == "node_created"
# <<<<<<< Updated upstream
#     assert msg["editor"]["user_id"] == test_user.pk, (
#         "server must override editor identity"
#     )
#     assert msg["node"] == {"id": "n1", "type": "python"}
# =======
#     assert (
#         msg["editor"]["user_id"] == test_user.pk
#     ), "server must override editor identity"
#     assert msg["node"] == {"id": 1, "type": "python"}
# >>>>>>> Stashed changes
#     assert "sender_channel" not in msg

#     assert await comm_a.receive_nothing(timeout=0.3), (
#         "sender must not receive its own relay"
#     )

#     await comm_a.disconnect()
#     await comm_b.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_node_updated_relayed_to_peer(test_graph, test_user, second_user):
#     comm_a = _make_communicator(test_graph.pk, test_user)
#     comm_b = _make_communicator(test_graph.pk, second_user)

#     await comm_a.connect()
#     await _drain_connect(comm_a)

#     await comm_b.connect()
#     await comm_a.receive_json_from()  # user_joined for second_user
#     await _drain_connect(comm_b)

#     node_payload = {"id": 2, "type": "agent", "label": "My Agent"}
#     await comm_a.send_json_to(
#         {
#             "type": "node_updated",
#             "node": node_payload,
# <<<<<<< Updated upstream
#             "list_key": "crew_node_list",
# =======
#             "list_key": "code_agent_node_list",
# >>>>>>> Stashed changes
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

#     msg = await comm_b.receive_json_from()
#     assert msg["type"] == "node_updated"
#     assert msg["node"] == node_payload

#     await comm_a.disconnect()
#     await comm_b.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_nodes_deleted_relayed_to_peer(test_graph, test_user, second_user):
#     comm_a = _make_communicator(test_graph.pk, test_user)
#     comm_b = _make_communicator(test_graph.pk, second_user)

#     await comm_a.connect()
#     await _drain_connect(comm_a)

#     await comm_b.connect()
#     await comm_a.receive_json_from()  # user_joined for second_user
#     await _drain_connect(comm_b)

#     await comm_a.send_json_to(
#         {
#             "type": "nodes_deleted",
#             "refs": [
# <<<<<<< Updated upstream
#                 {"list_key": "crew_node_list", "temp_id": "n1"},
#                 {"list_key": "crew_node_list", "temp_id": "n2"},
# =======
#                 {"list_key": "crew_node_list", "id": 1},
#                 {"list_key": "python_node_list", "id": 2},
# >>>>>>> Stashed changes
#             ],
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

#     msg = await comm_b.receive_json_from()
#     assert msg["type"] == "nodes_deleted"
# <<<<<<< Updated upstream
#     # The server serialises NodesDeletedMessage via model_dump() which includes
#     # all fields: id defaults to null in the wire representation.
#     assert msg["refs"] == [
#         {"list_key": "crew_node_list", "id": None, "temp_id": "n1"},
#         {"list_key": "crew_node_list", "id": None, "temp_id": "n2"},
#     ]
# =======
#     assert len(msg["refs"]) == 2
# >>>>>>> Stashed changes

#     await comm_a.disconnect()
#     await comm_b.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_connection_created_relayed_to_peer(test_graph, test_user, second_user):
#     comm_a = _make_communicator(test_graph.pk, test_user)
#     comm_b = _make_communicator(test_graph.pk, second_user)

#     await comm_a.connect()
#     await _drain_connect(comm_a)

#     await comm_b.connect()
#     await comm_a.receive_json_from()  # user_joined for second_user
#     await _drain_connect(comm_b)

#     connection_payload = {"id": 1, "start_node_id": 10, "end_node_id": 11}
#     await comm_a.send_json_to(
#         {
#             "type": "connection_created",
#             "connection": connection_payload,
#             "list_key": "edge_list",
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

#     msg = await comm_b.receive_json_from()
#     assert msg["type"] == "connection_created"
#     assert msg["connection"] == connection_payload

#     await comm_a.disconnect()
#     await comm_b.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_group_isolation_across_graphs(
#     test_graph, second_graph, test_user, second_user
# ):
#     comm_a = _make_communicator(test_graph.pk, test_user)
#     comm_b = _make_communicator(second_graph.pk, second_user)

#     await comm_a.connect()
#     await _drain_connect(comm_a)

#     await comm_b.connect()
#     await _drain_connect(comm_b)

#     await comm_a.send_json_to(
#         {
#             "type": "node_created",
# <<<<<<< Updated upstream
#             "node": {"id": "n1", "type": "python"},
# =======
#             "node": {"id": 1, "type": "python"},
# >>>>>>> Stashed changes
#             "list_key": "python_node_list",
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

#     assert await comm_b.receive_nothing(timeout=0.3), (
#         "message sent to graph A must not reach a consumer on graph B"
#     )

#     await comm_a.disconnect()
#     await comm_b.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_malformed_payload_returns_invalid_payload_error(test_graph, test_user):
#     communicator = _make_communicator(test_graph.pk, test_user)
#     await communicator.connect()
#     await _drain_connect(communicator)

#     # Send node_created without the required `node` field.
#     await communicator.send_json_to(
#         {
#             "type": "node_created",
#             "list_key": "crew_node_list",
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

#     msg = await communicator.receive_json_from()
#     assert msg["type"] == "error"
#     assert msg["code"] == "invalid_payload"

#     # Connection must survive a validation error — send an unknown type next.
#     await communicator.send_json_to({"type": "totally_unknown"})
#     msg = await communicator.receive_json_from()
#     assert msg["type"] == "error"
#     assert msg["code"] == "unknown_message_type"

#     await communicator.disconnect()


# # ---------------------------------------------------------------------------
# # server-seeded snapshot on connect
# # ---------------------------------------------------------------------------


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# <<<<<<< Updated upstream
# async def test_first_connector_receives_graph_state(test_graph, test_user):
#     """First connector (no cached snapshot) must receive graph_state seeded from DB."""
# =======
# async def test_first_connector_receives_graph_state_from_db(test_graph, test_user):
#     """First connector must receive graph_state seeded from DB (not request_state)."""
# >>>>>>> Stashed changes
#     communicator = _make_communicator(test_graph.pk, test_user)
#     await communicator.connect()

#     await communicator.receive_json_from()  # presence_state

#     msg = await communicator.receive_json_from()
# <<<<<<< Updated upstream
#     assert msg["type"] == "graph_state"
# =======
#     assert msg["type"] == "graph_state", (
#         "Server must seed from DB and send graph_state on first connect; "
#         f"got {msg['type']!r} instead"
#     )
#     # The snapshot must contain the canonical superset keys.
#     assert "save_version" in msg["flow"]
#     assert "crew_node_list" in msg["flow"]
#     assert "edge_list" in msg["flow"]
#     assert "deleted" in msg["flow"]
# >>>>>>> Stashed changes

#     await communicator.receive_json_from()  # user_joined
#     await communicator.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_second_connector_receives_same_graph_state_snapshot(
#     test_graph, test_user, second_user
# ):
#     """Second connector must receive graph_state carrying the live snapshot seeded from DB."""
#     comm1 = _make_communicator(test_graph.pk, test_user)
#     await comm1.connect()
#     await comm1.receive_json_from()  # presence_state
#     # Capture the graph_state message comm1 receives (seeded from DB).
#     graph_state_msg = await comm1.receive_json_from()
#     assert graph_state_msg["type"] == "graph_state"
#     db_snapshot = graph_state_msg["flow"]
#     await comm1.receive_json_from()  # user_joined

#     comm2 = _make_communicator(test_graph.pk, second_user)
#     await comm2.connect()
#     await comm1.receive_json_from()  # user_joined for second_user

#     await comm2.receive_json_from()  # presence_state
# <<<<<<< Updated upstream

#     msg = await comm2.receive_json_from()
#     assert msg["type"] == "graph_state"
#     # The second connector must receive the same DB-seeded snapshot as the first.
#     assert msg["flow"] == db_snapshot
# =======
#     msg2 = await comm2.receive_json_from()
#     assert msg2["type"] == "graph_state"
#     # Both should have the same save_version (seeded from same DB record).
#     assert msg1["flow"]["save_version"] == msg2["flow"]["save_version"]
# >>>>>>> Stashed changes

#     await comm2.receive_json_from()  # user_joined
#     await comm1.disconnect()
#     await comm2.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_deprecated_client_graph_state_seed_is_noop(test_graph, test_user):
#     """Client→Server graph_state is accepted silently but does not overwrite snapshot."""
#     comm = _make_communicator(test_graph.pk, test_user)
#     await comm.connect()
#     await _drain_connect(comm)

#     # Get the server-seeded snapshot save_version.
#     server_snapshot = await graph_state_service.get_snapshot(test_graph.pk)
#     assert server_snapshot is not None
#     original_version = server_snapshot["save_version"]

#     # Old client pushes its own flow — must be silently ignored.
#     old_client_flow = {"nodes": [{"id": "n1"}], "connections": []}
#     await comm.send_json_to({"type": "graph_state", "flow": old_client_flow})

#     # Wait briefly then verify snapshot was NOT replaced by old-client format.
#     import asyncio

#     await asyncio.sleep(0.05)
#     snapshot_after = await graph_state_service.get_snapshot(test_graph.pk)
#     assert snapshot_after is not None
#     assert "save_version" in snapshot_after, (
#         "Snapshot must remain in superset form after deprecated client seed"
#     )
#     assert snapshot_after["save_version"] == original_version

#     await comm.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_node_created_op_mutates_snapshot(test_graph, test_user):
#     """node_created op must be reflected in the stored snapshot."""
#     comm = _make_communicator(test_graph.pk, test_user)
#     await comm.connect()
#     await _drain_connect(comm)

# <<<<<<< Updated upstream
#     # The snapshot is auto-seeded from DB on connect. Send a node_created op.
#     await comm.send_json_to(
#         {
#             "type": "node_created",
#             "node": {"id": "n2", "type": "code"},
# =======
#     # The snapshot is already seeded from DB by connect; send a node_created op.
#     await comm.send_json_to(
#         {
#             "type": "node_created",
#             "node": {"temp_id": "tmp-1", "type": "python"},
# >>>>>>> Stashed changes
#             "list_key": "python_node_list",
#             "editor": {
#                 "user_id": test_user.pk,
#                 "display_name": "x",
#                 "avatar_url": None,
#             },
#         }
#     )

# <<<<<<< Updated upstream
#     async def _snapshot_has_n2():
#         snapshot = await graph_state_service.get_snapshot(test_graph.pk)
#         if snapshot is None:
#             return False
#         return any(n.get("id") == "n2" for n in snapshot.get("python_node_list", []))

#     assert await _wait_for(_snapshot_has_n2), "node_created op must update the snapshot"

#     await comm.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_graph_state_seed_does_not_overwrite_existing_snapshot(
#     test_graph, test_user
# ):
#     """Deprecated C→S graph_state messages must be silently ignored.

#     The server now seeds from DB on connect. Any client-originated graph_state
#     message is a no-op — it must not overwrite the live snapshot.
#     """
#     comm = _make_communicator(test_graph.pk, test_user)
#     await comm.connect()
#     await _drain_connect(comm)

#     # The snapshot was auto-seeded from DB on connect. Capture it.
#     snapshot_before = await graph_state_service.get_snapshot(test_graph.pk)
#     assert snapshot_before is not None

#     # Send two deprecated graph_state messages — both must be ignored.
#     await comm.send_json_to(
#         {"type": "graph_state", "flow": {"crew_node_list": [{"id": "overwrite1"}]}}
#     )
#     await comm.send_json_to(
#         {"type": "graph_state", "flow": {"crew_node_list": [{"id": "overwrite2"}]}}
#     )

#     # Allow the consumer to process both messages.
#     await _wait_for(lambda: graph_state_service.get_snapshot(test_graph.pk))

#     snapshot_after = await graph_state_service.get_snapshot(test_graph.pk)
#     assert snapshot_after is not None
#     # Snapshot must be unchanged — deprecated seeds are silently dropped.
#     assert snapshot_after == snapshot_before
# =======
#     async def _node_appears():
#         snap = await graph_state_service.get_snapshot(test_graph.pk)
#         if snap is None:
#             return False
#         return any(n.get("temp_id") == "tmp-1" for n in snap["python_node_list"])

#     assert await _wait_for(_node_appears), (
#         "Newly created node must appear in python_node_list after node_created op"
#     )
# >>>>>>> Stashed changes

#     await comm.disconnect()


# @pytest.mark.asyncio
# @pytest.mark.django_db(transaction=True)
# async def test_last_disconnect_clears_snapshot(test_graph, test_user):
#     """Snapshot must be cleared once the last editor leaves."""
#     comm = _make_communicator(test_graph.pk, test_user)
#     await comm.connect()
#     await _drain_connect(comm)

# <<<<<<< Updated upstream
#     # Snapshot is auto-seeded from DB on connect.
# =======
# >>>>>>> Stashed changes
#     assert await graph_state_service.get_snapshot(test_graph.pk) is not None

#     await comm.disconnect()

#     async def _snapshot_cleared():
#         return await graph_state_service.get_snapshot(test_graph.pk) is None

#     assert await _wait_for(_snapshot_cleared)
