"""
Tests for multi-tab (multiple connections per user) presence reference-counting.

Covers the two-tab scenarios:
- Closing one of two tabs must NOT broadcast user_left or remove the user.
- Closing both tabs DOES broadcast user_left and removes the user.
- Opening a second tab for an already-present user must NOT broadcast a duplicate user_joined.
- The second tab's connecting client still receives presence_state unconditionally.
- Unit-level coverage for the new has_user helper.
"""

import pytest

from tables.graph_collab.presence_service import GraphPresenceService, presence_service
from tests.graph_collab.conftest import _editor


# ---------------------------------------------------------------------------
# Unit tests: GraphPresenceService.has_user
# ---------------------------------------------------------------------------


def test_has_user_returns_true_when_user_is_present(presence_service):
    presence_service.add(graph_id=1, channel_name="ch-a", editor=_editor(user_id=10))
    assert presence_service.has_user(graph_id=1, user_id=10) is True


def test_has_user_returns_false_when_user_is_absent(presence_service):
    presence_service.add(graph_id=1, channel_name="ch-a", editor=_editor(user_id=10))
    assert presence_service.has_user(graph_id=1, user_id=99) is False


def test_has_user_returns_false_for_unknown_graph(presence_service):
    assert presence_service.has_user(graph_id=999, user_id=10) is False


def test_has_user_returns_false_after_only_channel_removed(presence_service):
    presence_service.add(graph_id=1, channel_name="ch-a", editor=_editor(user_id=10))
    presence_service.remove(graph_id=1, channel_name="ch-a")
    assert presence_service.has_user(graph_id=1, user_id=10) is False


def test_has_user_returns_true_after_one_of_two_channels_removed(presence_service):
    presence_service.add(graph_id=1, channel_name="ch-a", editor=_editor(user_id=10))
    presence_service.add(graph_id=1, channel_name="ch-b", editor=_editor(user_id=10))
    presence_service.remove(graph_id=1, channel_name="ch-a")
    assert presence_service.has_user(graph_id=1, user_id=10) is True


def test_has_user_is_scoped_to_graph(presence_service):
    """A user present in graph 1 must not appear as present in graph 2."""
    presence_service.add(graph_id=1, channel_name="ch-a", editor=_editor(user_id=10))
    assert presence_service.has_user(graph_id=2, user_id=10) is False


# ---------------------------------------------------------------------------
# Consumer integration tests: multi-tab scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_second_tab_does_not_broadcast_duplicate_user_joined(
    test_graph, test_user, second_user, make_communicator
):
    """
    Opening a second tab (second connection) for an already-present user must
    NOT send another user_joined to other participants.  The second tab itself
    still receives presence_state.
    """
    observer = make_communicator(test_graph.pk, second_user)
    tab1 = make_communicator(test_graph.pk, test_user)
    tab2 = make_communicator(test_graph.pk, test_user)

    # Observer connects first.
    await observer.connect()
    await observer.receive_json_from()  # presence_state
    await observer.receive_json_from()  # graph_state
    await observer.receive_json_from()  # user_joined (self)

    # test_user opens tab1 — observer receives user_joined.
    await tab1.connect()
    msg = await observer.receive_json_from()
    assert msg["type"] == "user_joined"
    assert msg["editor"]["user_id"] == test_user.pk
    await tab1.receive_json_from()  # presence_state to tab1
    await tab1.receive_json_from()  # graph_state to tab1
    await tab1.receive_json_from()  # user_joined (self) to tab1

    # test_user opens tab2 — observer must NOT receive another user_joined.
    # tab2 is a second tab for test_user (already_present=True), so no user_joined
    # is broadcast. tab2 only receives presence_state and graph_state (no user_joined).
    await tab2.connect()
    # tab2 must receive its own presence_state (unconditional).
    msg = await tab2.receive_json_from()
    assert msg["type"] == "presence_state"
    await (
        tab2.receive_json_from()
    )  # graph_state to tab2 (no user_joined — already present)

    # Observer queue must be empty — no duplicate user_joined.
    assert await observer.receive_nothing()

    await tab1.disconnect()
    await tab2.disconnect()
    await observer.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_closing_one_of_two_tabs_does_not_broadcast_user_left(
    test_graph, test_user, second_user, make_communicator
):
    """
    When a user has two tabs open, closing one tab must not broadcast
    user_left to other participants, and the user must remain in
    presence_service.
    """
    observer = make_communicator(test_graph.pk, second_user)
    tab1 = make_communicator(test_graph.pk, test_user)
    tab2 = make_communicator(test_graph.pk, test_user)

    await observer.connect()
    await observer.receive_json_from()  # presence_state
    await observer.receive_json_from()  # graph_state
    await observer.receive_json_from()  # user_joined (self)

    await tab1.connect()
    await observer.receive_json_from()  # user_joined for test_user
    await tab1.receive_json_from()  # presence_state to tab1
    await tab1.receive_json_from()  # graph_state to tab1
    await tab1.receive_json_from()  # user_joined (self) to tab1

    # tab2 is a second tab for test_user (already_present=True):
    # no user_joined broadcast, so tab2 only receives presence_state and graph_state.
    await tab2.connect()
    await tab2.receive_json_from()  # presence_state to tab2
    await tab2.receive_json_from()  # graph_state to tab2

    # Close only the first tab.
    await tab1.disconnect()

    # Observer must NOT receive user_left.
    assert await observer.receive_nothing()

    # User must still be tracked in presence_service.
    assert presence_service.has_user(test_graph.pk, test_user.pk)

    await tab2.disconnect()
    await observer.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_closing_both_tabs_broadcasts_user_left(
    test_graph, test_user, second_user, make_communicator
):
    """
    When a user closes all their tabs, user_left MUST be broadcast and the
    user must be absent from presence_service.
    """
    observer = make_communicator(test_graph.pk, second_user)
    tab1 = make_communicator(test_graph.pk, test_user)
    tab2 = make_communicator(test_graph.pk, test_user)

    await observer.connect()
    await observer.receive_json_from()  # presence_state
    await observer.receive_json_from()  # graph_state
    await observer.receive_json_from()  # user_joined (self)

    await tab1.connect()
    await observer.receive_json_from()  # user_joined for test_user
    await tab1.receive_json_from()  # presence_state
    await tab1.receive_json_from()  # graph_state to tab1
    await tab1.receive_json_from()  # user_joined (self) to tab1

    # tab2 is a second tab for test_user (already_present=True):
    # no user_joined broadcast, so tab2 only receives presence_state and graph_state.
    await tab2.connect()
    await tab2.receive_json_from()  # presence_state
    await tab2.receive_json_from()  # graph_state to tab2

    # Close first tab — silent.
    await tab1.disconnect()
    assert await observer.receive_nothing()

    # Close second (last) tab — user_left must fire.
    await tab2.disconnect()

    msg = await observer.receive_json_from()
    assert msg["type"] == "user_left"
    assert msg["user_id"] == test_user.pk

    # User must be gone from presence_service.
    assert not presence_service.has_user(test_graph.pk, test_user.pk)

    await observer.disconnect()
