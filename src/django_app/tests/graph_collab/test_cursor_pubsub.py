"""
Tests for cursor-moved routing via Redis pub/sub.

Verifies:
- cursor_moved messages travel via Redis pub/sub and are coalesced/batched;
  they never go through the channel-layer group_send.
- Coalescing: only the latest position per user is kept in the flush buffer.
- Echo suppression: a consumer does not receive its own cursor back.
- The cursor_batch down-message has the correct shape.
- cursor_moved is dispatched by receive_json and never falls through to the
  unknown_message_type branch.
- No empty cursor_batch is sent when there is no cursor activity.
"""

import asyncio

import pytest

from tests.graph_collab.conftest import (
    _drain_connect,
    collect_messages,
    connect_pair,
    receive_or_none,
    editor_payload,
)
from tables.graph_collab.constants import CURSOR_FLUSH_INTERVAL_SECONDS


# Multiplier bounds derived from CURSOR_FLUSH_INTERVAL_SECONDS — never a bare number.
_GENEROUS_ARRIVAL_TIMEOUT = CURSOR_FLUSH_INTERVAL_SECONDS * 10
_FLUSH_CYCLES_TO_AWAIT_FOR_ECHO_CHECK = CURSOR_FLUSH_INTERVAL_SECONDS * 2
_FLUSH_CYCLES_TO_AWAIT_FOR_EMPTY_BATCH_CHECK = CURSOR_FLUSH_INTERVAL_SECONDS * 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cursor_moved_payload(user, x: float, y: float) -> dict:
    return {
        "type": "cursor_moved",
        "x": x,
        "y": y,
        "editor": editor_payload(user),
    }


# ---------------------------------------------------------------------------
# Tests: cursor traffic stays off the channel layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_moved_does_not_go_through_channel_layer_group_send(
    test_graph, test_user, second_user, patch_redis_service
):
    """A cursor_moved from one client must NOT appear as a group_send relay.

    We verify this by checking that the channel layer is not involved:
    consumer B should only receive cursor data via the pub/sub batch path,
    never as an immediate channel-layer relay carrying type="cursor_moved".
    """
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 10.0, 20.0))

    messages = await collect_messages(comm_b, timeout=_GENEROUS_ARRIVAL_TIMEOUT)
    received_types = [msg["type"] for msg in messages]

    assert "cursor_moved" not in received_types, (
        "cursor_moved must not travel via the channel layer; "
        "only cursor_batch is allowed"
    )

    await comm_a.disconnect()
    await comm_b.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_batch_received_by_peer_with_correct_shape(
    test_graph, test_user, second_user, patch_redis_service
):
    """Consumer B must receive a cursor_batch with x, y, and editor fields."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 42.5, 99.1))

    msg = await receive_or_none(comm_b, timeout=_GENEROUS_ARRIVAL_TIMEOUT)
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
    test_graph, test_user, second_user, patch_redis_service
):
    """Send two cursor_moved for the same user before a flush; batch must
    contain only the second (latest) position."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    # Two rapid cursor updates from user_a — only the second should survive.
    await comm_a.send_json_to(_cursor_moved_payload(test_user, 1.0, 1.0))
    await comm_a.send_json_to(_cursor_moved_payload(test_user, 2.0, 2.0))

    msg = await receive_or_none(comm_b, timeout=_GENEROUS_ARRIVAL_TIMEOUT)
    assert msg is not None, "comm_b should have received a cursor_batch"
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
async def test_consumer_does_not_receive_own_cursor(
    test_graph, test_user, second_user, patch_redis_service
):
    """A user must NOT receive their own cursor position back in any batch."""
    comm_a, comm_b = await connect_pair(test_graph, test_user, second_user)

    await comm_a.send_json_to(_cursor_moved_payload(test_user, 5.0, 5.0))

    # A negative assertion needs to wait out at least one full flush cycle
    # before concluding nothing came.
    await asyncio.sleep(_FLUSH_CYCLES_TO_AWAIT_FOR_ECHO_CHECK)

    echo = await receive_or_none(comm_a, timeout=CURSOR_FLUSH_INTERVAL_SECONDS)
    assert echo is None, f"comm_a must not receive its own cursor; got: {echo}"

    await comm_a.disconnect()
    await comm_b.disconnect()


# ---------------------------------------------------------------------------
# Tests: cursor_moved is not treated as an unknown message type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_cursor_moved_does_not_return_unknown_message_error(
    test_graph, test_user, make_communicator, patch_redis_service
):
    """cursor_moved is dispatched by receive_json and never falls through to
    the unknown_message_type branch."""
    communicator = make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    await communicator.send_json_to(_cursor_moved_payload(test_user, 3.0, 7.0))

    msg = await receive_or_none(
        communicator, timeout=_FLUSH_CYCLES_TO_AWAIT_FOR_ECHO_CHECK
    )
    assert msg is None or msg.get("type") != "error", (
        f"cursor_moved must not be treated as unknown message type; got: {msg}"
    )

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# Tests: no empty cursor_batch is sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_no_empty_cursor_batch_sent_when_no_cursors(
    test_graph, test_user, make_communicator, patch_redis_service
):
    """Without any cursor activity, the flush loop must not send empty batches."""
    communicator = make_communicator(test_graph.pk, test_user)
    await communicator.connect()
    await _drain_connect(communicator)

    # A negative assertion needs to wait out several flush cycles with no
    # cursor traffic before concluding nothing came.
    await asyncio.sleep(_FLUSH_CYCLES_TO_AWAIT_FOR_EMPTY_BATCH_CHECK)

    msg = await receive_or_none(communicator, timeout=CURSOR_FLUSH_INTERVAL_SECONDS)
    assert msg is None, f"No cursor_batch should be sent without activity; got: {msg}"

    await communicator.disconnect()
