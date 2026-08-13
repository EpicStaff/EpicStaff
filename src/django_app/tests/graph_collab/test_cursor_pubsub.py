"""
Tests for cursor-moved routing via Redis pub/sub.

Verifies:
- cursor_moved messages do NOT travel through the channel-layer group_send.
- Coalescing: only the latest position per user is kept in the flush buffer.
- Echo suppression: a consumer does not receive its own cursor back.
- The cursor_batch down-message has the correct shape.
- Critical messages (node_locked) still relay correctly via the channel layer
  (regression guard — the channel layer must remain unaffected).
"""

import asyncio
import json

import fakeredis.aioredis
import pytest

from tests.graph_collab.conftest import _drain_connect, _make_communicator
from tables.graph_collab.constants import CURSOR_FLUSH_INTERVAL_SECONDS
from tables.graph_collab.consumers import GraphEditConsumer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cursor_redis():
    """Shared fakeredis instance used across consumers in a single test.

    All consumers that connect to the same graph must share one FakeRedis
    so that publish() from one is visible via listen() on another.
    """
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_cursor_redis_service(fake_cursor_redis, monkeypatch):
    """Replace RedisService.async_redis_client with the in-memory fake.

    The consumer imports RedisService lazily inside methods, so we patch
    the property on the singleton class to guarantee any call site gets the fake.
    """
    from tables.services import redis_service as _rs_module

    monkeypatch.setattr(
        type(_rs_module.RedisService()),
        "async_redis_client",
        property(lambda self: fake_cursor_redis),
    )
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _connect_pair(graph, user_a, user_b):
    """Connect two communicators and drain all connect-time messages."""
    comm_a = _make_communicator(graph.pk, user_a)
    comm_b = _make_communicator(graph.pk, user_b)

    await comm_a.connect()
    await _drain_connect(comm_a)

    await comm_b.connect()
    await comm_a.receive_json_from()  # user_joined for user_b
    await _drain_connect(comm_b)

    return comm_a, comm_b


def _cursor_moved_payload(user, x: float, y: float) -> dict:
    return {
        "type": "cursor_moved",
        "x": x,
        "y": y,
        "editor": {
            "user_id": user.pk,
            "display_name": user.display_name,
            "avatar_url": None,
        },
    }


async def _wait_for_message(
    communicator, timeout: float = 1.0, poll: float = 0.05
) -> dict | None:
    """Poll a communicator for a message, returning None on timeout."""
    elapsed = 0.0
    while elapsed < timeout:
        try:
            return await asyncio.wait_for(
                communicator.receive_json_from(), timeout=poll
            )
        except asyncio.TimeoutError:
            elapsed += poll
    return None


# ---------------------------------------------------------------------------
# Tests: cursor traffic stays off the channel layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_moved_does_not_go_through_channel_layer_group_send(
    test_graph, test_user, second_user, fake_cursor_redis
):
    """A cursor_moved from one client must NOT appear as a group_send relay.

    We verify this by checking that the channel layer is not involved:
    consumer B should only receive cursor data via the pub/sub batch path,
    never as an immediate channel-layer relay carrying type="cursor_moved".
    Consumer A sends a cursor; we verify that for the entire flush interval
    no message of type "cursor_moved" arrives (only "cursor_batch" may appear).
    """
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 10.0, 20.0))

    # Wait long enough for a flush cycle to complete.
    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 2)

    # Collect everything comm_b received.
    received_types = []
    while True:
        msg = await _wait_for_message(comm_b, timeout=0.1, poll=0.05)
        if msg is None:
            break
        received_types.append(msg["type"])

    assert "cursor_moved" not in received_types, (
        "cursor_moved must not travel via the channel layer; "
        "only cursor_batch is allowed"
    )

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_batch_received_by_peer_with_correct_shape(
    test_graph, test_user, second_user
):
    """Consumer B must receive a cursor_batch with x, y, and editor fields."""
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 42.5, 99.1))

    # Wait beyond one flush interval.
    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 2)

    msg = await _wait_for_message(comm_b, timeout=1.0)
    assert msg is not None, "comm_b should have received a cursor_batch"
    assert msg["type"] == "cursor_batch"
    cursors = msg["cursors"]
    assert len(cursors) == 1
    cursor = cursors[0]
    assert cursor["x"] == 42.5
    assert cursor["y"] == 99.1
    assert "editor" in cursor
    assert cursor["editor"]["user_id"] == test_user.pk

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Tests: coalescing — only latest position per user survives the flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_coalescing_keeps_only_latest_position(
    test_graph, test_user, second_user
):
    """Send two cursor_moved for the same user before a flush; batch must
    contain only the second (latest) position."""
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    # Two rapid cursor updates from user_a — only the second should survive.
    await comm_a.send_json_to(_cursor_moved_payload(test_user, 1.0, 1.0))
    await comm_a.send_json_to(_cursor_moved_payload(test_user, 2.0, 2.0))

    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 2)

    msg = await _wait_for_message(comm_b, timeout=1.0)
    assert msg is not None
    assert msg["type"] == "cursor_batch"
    cursors = msg["cursors"]

    # Only one entry for user_a — the latest coordinates.
    user_a_cursors = [c for c in cursors if c["editor"]["user_id"] == test_user.pk]
    assert len(user_a_cursors) == 1
    assert user_a_cursors[0]["x"] == 2.0
    assert user_a_cursors[0]["y"] == 2.0

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Tests: echo suppression — consumer does not see own cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_consumer_does_not_receive_own_cursor(test_graph, test_user, second_user):
    """A user must NOT receive their own cursor position back in any batch."""
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 5.0, 5.0))

    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 2)

    # comm_a should receive nothing (echo suppression).
    echo = await _wait_for_message(comm_a, timeout=0.3, poll=0.05)
    assert echo is None, f"comm_a must not receive its own cursor; got: {echo}"

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Tests: critical messages still relay correctly (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_node_locked_still_relays_via_channel_layer(
    test_graph, test_user, second_user
):
    """node_locked must still reach the peer via the channel layer — unaffected
    by the cursor refactor."""
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(
        {
            "type": "node_locked",
            "node_id": "n1",
            "field": "label",
            "editor": {
                "user_id": test_user.pk,
                "display_name": test_user.display_name,
                "avatar_url": None,
            },
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_locked"
    assert msg["node_id"] == "n1"
    assert msg["field"] == "label"
    assert msg["editor"]["user_id"] == test_user.pk

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_node_created_still_relays_via_channel_layer(
    test_graph, test_user, second_user
):
    """node_created must still reach the peer immediately via the channel layer."""
    comm_a, comm_b = await _connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(
        {
            "type": "node_created",
            "node": {"id": 99, "type": "agent"},
            "list_key": "code_agent_node_list",
            "editor": {
                "user_id": test_user.pk,
                "display_name": test_user.display_name,
                "avatar_url": None,
            },
        }
    )

    msg = await comm_b.receive_json_from()
    assert msg["type"] == "node_created"
    assert msg["node"]["id"] == 99
    assert "sender_channel" not in msg

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Tests: cursor_moved is not treated as an unknown message type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_moved_does_not_return_unknown_message_error(
    test_graph, test_user
):
    """cursor_moved must be handled by the consumer — not rejected as unknown."""
    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    await communicator.send_json_to(_cursor_moved_payload(test_user, 3.0, 7.0))

    # Should receive nothing (no error, no echo) after a brief wait.
    msg = await _wait_for_message(communicator, timeout=0.3, poll=0.05)
    # Only a cursor_batch would be acceptable here (from self-publish); but
    # echo suppression means the sender user is filtered out, so nothing arrives.
    if msg is not None:
        assert msg["type"] != "error", (
            f"cursor_moved must not return an error; got: {msg}"
        )

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Tests: no empty cursor_batch is sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_no_empty_cursor_batch_sent_when_no_cursors(test_graph, test_user):
    """Without any cursor activity, the flush loop must not send empty batches."""
    communicator = _make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    # Wait for several flush cycles with no cursor traffic.
    await asyncio.sleep(CURSOR_FLUSH_INTERVAL_SECONDS * 3)

    msg = await _wait_for_message(communicator, timeout=0.1, poll=0.05)
    assert msg is None, f"No cursor_batch should be sent without activity; got: {msg}"

    await communicator.disconnect()
