"""Unit tests for NodeLockService (pure in-memory, no DB/Redis needed)."""

import pytest

from tables.graph_collab.lock_service import NodeLockService
from tests.graph_collab.conftest import _editor


@pytest.fixture
def lock_service():
    return NodeLockService()


@pytest.fixture
def editor_a():
    return _editor(user_id=1, name="Alice")


@pytest.fixture
def editor_b():
    return _editor(user_id=2, name="Bob")


GRAPH_ID = 42
NODE_ID = "node-1"
FIELD = "label"
CHANNEL_A = "specific.channel.abc"
CHANNEL_B = "specific.channel.xyz"


# ---------------------------------------------------------------------------
# try_lock
# ---------------------------------------------------------------------------


def test_try_lock_on_free_node_succeeds_and_records_entry(lock_service, editor_a):
    granted = lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    assert granted is True
    entry = lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD)
    assert entry is not None
    assert entry.editor == editor_a
    assert entry.channel == CHANNEL_A


def test_try_lock_second_channel_loses_race_and_does_not_replace_holder(
    lock_service, editor_a, editor_b
):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    granted = lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_b, CHANNEL_B)
    assert granted is False
    entry = lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD)
    assert entry is not None
    assert entry.editor == editor_a
    assert entry.channel == CHANNEL_A


def test_try_lock_same_channel_relock_succeeds_and_updates_entry(
    lock_service, editor_a, editor_b
):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    granted = lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_b, CHANNEL_A)
    assert granted is True
    entry = lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD)
    assert entry is not None
    assert entry.editor == editor_b
    assert entry.channel == CHANNEL_A


# ---------------------------------------------------------------------------
# get_holder
# ---------------------------------------------------------------------------


def test_get_holder_returns_none_for_unlocked_node(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    assert lock_service.get_holder(GRAPH_ID, "node-2", FIELD) is None
    assert lock_service.get_holder(GRAPH_ID, NODE_ID, "description") is None
    assert lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD) is not None


def test_get_holder_returns_none_for_unknown_graph(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    assert lock_service.get_holder(999, NODE_ID, FIELD) is None
    assert lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD) is not None


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_by_owner_returns_true_and_clears_lock(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    released = lock_service.release(GRAPH_ID, NODE_ID, FIELD, CHANNEL_A)
    assert released is True
    assert lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD) is None


def test_release_by_non_owner_returns_false_and_leaves_lock_intact(
    lock_service, editor_a
):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    released = lock_service.release(GRAPH_ID, NODE_ID, FIELD, CHANNEL_B)
    assert released is False
    entry = lock_service.get_holder(GRAPH_ID, NODE_ID, FIELD)
    assert entry is not None
    assert entry.editor == editor_a
    assert entry.channel == CHANNEL_A


def test_release_on_unheld_node_returns_false(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, "node-2", FIELD, editor_a, CHANNEL_A)
    assert lock_service.release(GRAPH_ID, NODE_ID, FIELD, CHANNEL_A) is False
    assert lock_service.release(GRAPH_ID, "node-2", "description", CHANNEL_A) is False
    assert lock_service.get_holder(GRAPH_ID, "node-2", FIELD) is not None


def test_release_cleans_up_empty_graph_dict(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    lock_service.release(GRAPH_ID, NODE_ID, FIELD, CHANNEL_A)
    assert GRAPH_ID not in lock_service._store


# ---------------------------------------------------------------------------
# release_all_for_channel
# ---------------------------------------------------------------------------


def test_release_all_for_channel_returns_held_node_field_pairs(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, "node-1", FIELD, editor_a, CHANNEL_A)
    lock_service.try_lock(GRAPH_ID, "node-2", FIELD, editor_a, CHANNEL_A)
    released = lock_service.release_all_for_channel(GRAPH_ID, CHANNEL_A)
    assert set(released) == {("node-1", FIELD), ("node-2", FIELD)}


def test_release_all_for_channel_removes_locks(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, "node-1", FIELD, editor_a, CHANNEL_A)
    lock_service.try_lock(GRAPH_ID, "node-2", FIELD, editor_a, CHANNEL_A)
    lock_service.release_all_for_channel(GRAPH_ID, CHANNEL_A)
    assert lock_service.get_holder(GRAPH_ID, "node-1", FIELD) is None
    assert lock_service.get_holder(GRAPH_ID, "node-2", FIELD) is None


def test_release_all_for_channel_does_not_release_other_channels(
    lock_service, editor_a, editor_b
):
    lock_service.try_lock(GRAPH_ID, "node-1", FIELD, editor_a, CHANNEL_A)
    lock_service.try_lock(GRAPH_ID, "node-2", FIELD, editor_b, CHANNEL_B)
    released = lock_service.release_all_for_channel(GRAPH_ID, CHANNEL_A)
    assert released == [("node-1", FIELD)]
    assert lock_service.get_holder(GRAPH_ID, "node-2", FIELD) is not None


def test_release_all_for_channel_returns_empty_for_no_locks(
    lock_service, editor_a, editor_b
):
    lock_service.try_lock(GRAPH_ID, "node-1", FIELD, editor_b, CHANNEL_B)
    lock_service.try_lock(GRAPH_ID + 1, "node-1", FIELD, editor_a, CHANNEL_A)
    released = lock_service.release_all_for_channel(GRAPH_ID, CHANNEL_A)
    assert released == []
    assert lock_service.get_holder(GRAPH_ID, "node-1", FIELD) is not None
    assert lock_service.get_holder(GRAPH_ID + 1, "node-1", FIELD) is not None


def test_release_all_for_channel_cleans_up_empty_graph_dict(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    lock_service.release_all_for_channel(GRAPH_ID, CHANNEL_A)
    assert GRAPH_ID not in lock_service._store


# ---------------------------------------------------------------------------
# Graph isolation
# ---------------------------------------------------------------------------


def test_locks_are_isolated_per_graph(lock_service, editor_a, editor_b):
    """A lock on graph A must not interfere with the same node on graph B."""
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    granted = lock_service.try_lock(GRAPH_ID + 1, NODE_ID, FIELD, editor_b, CHANNEL_B)
    assert granted is True


# ---------------------------------------------------------------------------
# get_all_locks
# ---------------------------------------------------------------------------


def test_get_all_locks_returns_empty_dict_for_unknown_graph(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    assert lock_service.get_all_locks(999) == {}
    assert lock_service.get_all_locks(GRAPH_ID) != {}


def test_get_all_locks_returns_all_held_locks(lock_service, editor_a, editor_b):
    lock_service.try_lock(GRAPH_ID, "node-1", FIELD, editor_a, CHANNEL_A)
    lock_service.try_lock(GRAPH_ID, "node-2", FIELD, editor_b, CHANNEL_B)
    result = lock_service.get_all_locks(GRAPH_ID)
    assert set(result.keys()) == {"node-1", "node-2"}
    assert result["node-1"][FIELD].editor == editor_a
    assert result["node-2"][FIELD].editor == editor_b


def test_get_all_locks_returns_copy_not_internal_reference(lock_service, editor_a):
    lock_service.try_lock(GRAPH_ID, NODE_ID, FIELD, editor_a, CHANNEL_A)
    result = lock_service.get_all_locks(GRAPH_ID)
    result["injected"] = None
    assert "injected" not in lock_service._store[GRAPH_ID]


# ---------------------------------------------------------------------------
# Field-level independence
# ---------------------------------------------------------------------------


def test_different_fields_on_same_node_are_independent(
    lock_service, editor_a, editor_b
):
    """Two different fields on the same node can be locked independently."""
    lock_service.try_lock(GRAPH_ID, NODE_ID, "label", editor_a, CHANNEL_A)
    granted = lock_service.try_lock(
        GRAPH_ID, NODE_ID, "description", editor_b, CHANNEL_B
    )
    assert granted is True
    assert lock_service.get_holder(GRAPH_ID, NODE_ID, "label").channel == CHANNEL_A
    assert (
        lock_service.get_holder(GRAPH_ID, NODE_ID, "description").channel == CHANNEL_B
    )


# ---------------------------------------------------------------------------
# lock_service.release_all — direct unit coverage (pure in-memory, no DB)
# ---------------------------------------------------------------------------


def test_lock_service_release_all_returns_every_pair_and_clears_the_graph(
    lock_service, editor_a
):
    lock_service.try_lock(GRAPH_ID, "node-1", "label", editor_a, "chan-1")
    lock_service.try_lock(GRAPH_ID, "node-1", "description", editor_a, "chan-1")
    lock_service.try_lock(GRAPH_ID, "node-2", "label", editor_a, "chan-2")
    lock_service.try_lock(
        GRAPH_ID + 1, "node-1", "label", editor_a, "chan-3"
    )  # other graph

    released = lock_service.release_all(GRAPH_ID)

    assert set(released) == {
        ("node-1", "label"),
        ("node-1", "description"),
        ("node-2", "label"),
    }
    assert lock_service.get_all_locks(GRAPH_ID) == {}
    assert 999 not in lock_service._store
    # A different graph's locks must be untouched.
    assert lock_service.get_holder(GRAPH_ID + 1, "node-1", "label") is not None


def test_lock_service_release_all_on_graph_with_no_locks_returns_empty_list(
    lock_service, editor_a
):
    lock_service.try_lock(GRAPH_ID, "node-1", "label", editor_a, "chan-1")
    assert lock_service.release_all(424242) == []
    assert lock_service.get_holder(GRAPH_ID, "node-1", "label") is not None
