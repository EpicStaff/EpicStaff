"""Consumer-level tests for authoritative node locks."""

import pytest
from django.test import override_settings

from tables.graph_collab import lock_service as _ls_module

from tests.graph_collab.conftest import (
    _drain_connect,
    connect_pair,
    wait_for,
    editor_payload,
)


async def drain_connect_with_locks(communicator) -> dict:
    """Consume 4 initial messages when locks are active; return the lock_state message."""
    received = {}
    for _ in range(4):
        msg = await communicator.receive_json_from()
        received[msg["type"]] = msg
    assert "presence_state" in received
    assert "user_joined" in received
    assert "graph_state" in received
    assert "lock_state" in received
    return received["lock_state"]


def lock_message(message_type: str, node_id: str, field: str, user) -> dict:
    """`node_locked`/`node_unlocked` payload as sent by a test client."""
    return {
        "type": message_type,
        "node_id": node_id,
        "field": field,
        "editor": editor_payload(user),
    }


# ---------------------------------------------------------------------------
# Lock claim: winner + loser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_lock_winner_relay_reaches_peer(test_graph, test_user, second_user):
    """The first client to claim a node lock should have the event relayed to peers.

    Also covers the invariant that lock traffic relays via the channel layer,
    not the Redis cursor pub/sub path.
    """
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_locked"
    assert msg["node_id"] == "node-1"
    assert msg["field"] == "label"
    assert msg["editor"]["user_id"] == test_user.pk
    assert "sender_channel" not in msg

    # Winner must NOT echo to itself.
    assert await comm_a.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_lock_loser_receives_corrective_signal_naming_winner(
    test_graph, test_user, second_user
):
    """Loser should receive a node_locked from the server describing the winner."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # comm_a wins the lock.
    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))
    # Drain comm_b's relay of the winner's lock.
    winner_relay = await comm_b.receive_json_from()
    assert winner_relay["type"] == "node_locked"
    # comm_a must not echo to itself.
    assert await comm_a.receive_nothing(timeout=0.1)

    # comm_b tries to claim the same node — should lose.
    await comm_b.send_json_to(
        lock_message("node_locked", "node-1", "label", second_user)
    )

    corrective = await comm_b.receive_json_from()
    assert corrective["type"] == "node_locked"
    assert corrective["node_id"] == "node-1"
    assert corrective["field"] == "label"
    # The corrective signal must name the WINNER (test_user), not the loser.
    assert corrective["editor"]["user_id"] == test_user.pk

    # comm_a must not receive anything (loser's failed claim is silent to others).
    assert await comm_a.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_lock_winner_identity_is_server_overridden(
    test_graph, test_user, second_user
):
    """Server must override editor identity on node_locked, same as other relay ops."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    spoofed_editor = {"user_id": 9999, "display_name": "spoof", "avatar_url": None}
    await comm_a.send_json_to(
        {
            "type": "node_locked",
            "node_id": "node-spoof",
            "field": "label",
            "editor": spoofed_editor,
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["editor"]["user_id"] == test_user.pk, "server must override editor"

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Lock release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_explicit_release_broadcasts_to_peers(test_graph, test_user, second_user):
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # Acquire the lock.
    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))
    await comm_b.receive_json_from()  # relay of lock claim

    # Release it.
    await comm_a.send_json_to(
        lock_message("node_unlocked", "node-1", "label", test_user)
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_unlocked"
    assert msg["node_id"] == "node-1"
    assert msg["field"] == "label"
    assert "sender_channel" not in msg

    # Sender must not echo.
    assert await comm_a.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_spurious_release_by_non_owner_is_silent(
    test_graph, test_user, second_user
):
    """A non-owner sending node_unlocked for someone else's lock must be silently ignored."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # comm_a holds the lock.
    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))
    await comm_b.receive_json_from()  # relay of lock claim

    # comm_b tries to release comm_a's lock — must be rejected silently.
    await comm_b.send_json_to(
        lock_message("node_unlocked", "node-1", "label", second_user)
    )

    # Neither client should receive anything.
    assert await comm_a.receive_nothing(timeout=0.3)
    assert await comm_b.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Disconnect auto-release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_disconnect_releases_locks_and_broadcasts_node_unlocked(
    test_graph, test_user, second_user
):
    """Disconnecting client's locks must be released and node_unlocked broadcast to peers."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # comm_a acquires two locks.
    for node_id in ("node-1", "node-2"):
        await comm_a.send_json_to(
            lock_message("node_locked", node_id, "label", test_user)
        )
        await comm_b.receive_json_from()  # drain relay

    await comm_a.disconnect()

    # comm_b should receive node_unlocked + user_left (order may vary).
    received = []
    for _ in range(3):  # 2 unlocks + 1 user_left
        msg = await comm_b.receive_json_from()
        received.append(msg)

    unlock_msgs = [m for m in received if m["type"] == "node_unlocked"]
    user_left_msgs = [m for m in received if m["type"] == "user_left"]

    assert len(unlock_msgs) == 2
    unlocked_node_ids = {m["node_id"] for m in unlock_msgs}
    assert unlocked_node_ids == {"node-1", "node-2"}
    for m in unlock_msgs:
        assert m["field"] == "label"

    assert len(user_left_msgs) == 1
    assert user_left_msgs[0]["user_id"] == test_user.pk

    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_disconnect_lock_registry_is_empty_after(
    test_graph, test_user, make_communicator
):
    """After the only client disconnects, the lock registry for that graph is empty."""
    comm = make_communicator(test_graph.pk, test_user)
    await comm.connect()
    await _drain_connect(comm)

    await comm.send_json_to(lock_message("node_locked", "node-1", "label", test_user))

    async def _lock_registered():
        return (
            _ls_module.lock_service.get_holder(test_graph.pk, "node-1", "label")
            is not None
        )

    assert await wait_for(_lock_registered), "lock was not registered in time"

    await comm.disconnect()

    async def _lock_released():
        return (
            _ls_module.lock_service.get_holder(test_graph.pk, "node-1", "label") is None
        )

    assert await wait_for(_lock_released), "lock was not released after disconnect"


# ---------------------------------------------------------------------------
# Backstop timeout auto-release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(GRAPH_LOCK_TIMEOUT_SECONDS=0)
async def test_backstop_timeout_fires_node_unlocked(test_graph, test_user, second_user):
    """With GRAPH_LOCK_TIMEOUT_SECONDS=0 the backstop timer fires immediately."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(
        lock_message("node_locked", "node-timeout", "label", test_user)
    )
    # Drain the relay of the lock claim.
    lock_relay = await comm_b.receive_json_from()
    assert lock_relay["type"] == "node_locked"

    # The backstop fires immediately (timeout=0); receive_json_from raises
    # asyncio.TimeoutError if nothing arrives within its default window.
    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_unlocked"
    assert msg["node_id"] == "node-timeout"
    assert msg["field"] == "label"

    # Lock must be cleared from the registry.
    assert (
        _ls_module.lock_service.get_holder(test_graph.pk, "node-timeout", "label")
        is None
    )

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Invalid payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_node_locked_invalid_payload_returns_error(
    test_graph, test_user, make_communicator
):
    comm = make_communicator(test_graph.pk, test_user)
    await comm.connect()
    await _drain_connect(comm)

    # Send node_locked without required node_id.
    await comm.send_json_to(
        {
            "type": "node_locked",
            "editor": editor_payload(test_user),
        }
    )

    msg = await comm.receive_json_from()
    assert msg["type"] == "error"
    assert msg["code"] == "invalid_payload"

    await comm.disconnect()


# ---------------------------------------------------------------------------
# Late-join lock state delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_late_joiner_receives_lock_state_with_active_locks(
    test_graph, test_user, second_user, make_communicator
):
    comm_a = make_communicator(test_graph.pk, test_user)
    comm_b = make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))

    async def _lock_registered():
        return (
            _ls_module.lock_service.get_holder(test_graph.pk, "node-1", "label")
            is not None
        )

    assert await wait_for(_lock_registered), "lock was not registered in time"

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined broadcast

    lock_state_msg = await drain_connect_with_locks(comm_b)

    assert lock_state_msg["type"] == "lock_state"
    assert "node-1" in lock_state_msg["locks"]
    assert "label" in lock_state_msg["locks"]["node-1"]
    assert lock_state_msg["locks"]["node-1"]["label"]["user_id"] == test_user.pk

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_late_joiner_receives_all_active_locks(
    test_graph, test_user, second_user, make_communicator
):
    comm_a = make_communicator(test_graph.pk, test_user)
    comm_b = make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    node_ids = ("node-1", "node-2", "node-3")
    for node_id in node_ids:
        await comm_a.send_json_to(
            lock_message("node_locked", node_id, "label", test_user)
        )

    async def _all_locks_registered():
        return all(
            _ls_module.lock_service.get_holder(test_graph.pk, node_id, "label")
            is not None
            for node_id in node_ids
        )

    assert await wait_for(_all_locks_registered), "locks were not registered in time"

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined

    lock_state_msg = await drain_connect_with_locks(comm_b)
    assert set(lock_state_msg["locks"].keys()) == {"node-1", "node-2", "node-3"}

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_first_joiner_does_not_receive_lock_state(
    test_graph, test_user, make_communicator
):
    comm = make_communicator(test_graph.pk, test_user)
    await comm.connect()
    await _drain_connect(comm)
    assert await comm.receive_nothing(timeout=0.3)
    await comm.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_late_joiner_no_lock_state_after_all_locks_released(
    test_graph, test_user, second_user, make_communicator
):
    comm_a = make_communicator(test_graph.pk, test_user)
    comm_b = make_communicator(test_graph.pk, second_user)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_a.send_json_to(lock_message("node_locked", "node-1", "label", test_user))

    async def _lock_registered():
        return (
            _ls_module.lock_service.get_holder(test_graph.pk, "node-1", "label")
            is not None
        )

    assert await wait_for(_lock_registered), "lock was not registered in time"

    await comm_a.send_json_to(
        lock_message("node_unlocked", "node-1", "label", test_user)
    )

    async def _lock_released():
        return (
            _ls_module.lock_service.get_holder(test_graph.pk, "node-1", "label") is None
        )

    assert await wait_for(_lock_released), "lock was not released in time"

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined

    await _drain_connect(comm_b)
    assert await comm_b.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()
