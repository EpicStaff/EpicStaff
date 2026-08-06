"""Tests for the CAS ("compare-and-swap") precondition on partial node_updated
ops: NodeUpdatedMessage.expected lets a client (e.g. an undo action) assert
the value it believes the server currently holds for each changed field; a
mismatch rejects the op with reason "precondition_failed" and leaves the
snapshot untouched.
"""

import pytest
from pydantic import ValidationError

from tables.graph_collab.graph_state_service import OpResult, OpStatus
from tables.graph_collab.protocol import NodeUpdatedMessage

from tests.graph_collab.conftest import _drain_connect, _editor, _make_communicator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _partial_update(
    node: dict,
    list_key: str,
    changed_fields: list[str],
    expected: dict | None = None,
    op_id: str | None = None,
) -> NodeUpdatedMessage:
    return NodeUpdatedMessage(
        node=node,
        list_key=list_key,
        editor=_editor(),
        changed_fields=changed_fields,
        expected=expected,
        op_id=op_id,
    )


# ---------------------------------------------------------------------------
# CAS pass / applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_pass_applies(live_state_service, base_snapshot):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[{"id": 5, "crew_id": 7, "node_name": "Old Name"}]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "node_name": "New Name"},
        list_key="crew_node_list",
        changed_fields=["node_name"],
        expected={"node_name": "Old Name"},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["node_name"] == "New Name"


# ---------------------------------------------------------------------------
# CAS mismatch — scalar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_scalar_mismatch_rejects_without_mutating_snapshot(
    live_state_service, base_snapshot
):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[{"id": 5, "crew_id": 7, "node_name": "Current Name"}]
        ),
    )
    revision_before = live_state_service.current_revision(1)

    msg = _partial_update(
        node={"id": 5, "node_name": "New Name"},
        list_key="crew_node_list",
        changed_fields=["node_name"],
        expected={"node_name": "Stale Name"},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "precondition_failed"
    assert result.relay is False
    assert result.details == {"mismatched_fields": ["node_name"]}

    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["node_name"] == "Current Name"
    assert live_state_service.current_revision(1) == revision_before


# ---------------------------------------------------------------------------
# CAS mismatch — metadata sub-key, sibling metadata compared freely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_position_mismatch_reports_wire_name_ignores_sibling_metadata(
    live_state_service, base_snapshot
):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[
                {
                    "id": 5,
                    "node_name": "Crew #1",
                    "metadata": {
                        "position": {"x": 0, "y": 0},
                        "color": "#actual-color-differs-from-expected",
                        "nodeNumber": 3,
                    },
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "position": {"x": 100, "y": 200}},
        list_key="crew_node_list",
        changed_fields=["position"],
        expected={"position": {"x": 999, "y": 999}},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "precondition_failed"
    assert result.details == {"mismatched_fields": ["position"]}

    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["metadata"]["position"] == {"x": 0, "y": 0}


# ---------------------------------------------------------------------------
# CAS — declared-but-absent field is still validated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_validates_declared_field_absent_from_node_payload(
    live_state_service, base_snapshot
):
    """A field can be declared in changed_fields (and therefore carried in
    expected) while the op's node payload doesn't actually include it — the
    overlay silently drops it, but CAS must still validate the client's
    stated belief about that field's current value."""
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[{"id": 5, "crew_id": 7, "node_name": "Current Name"}]
        ),
    )

    msg = _partial_update(
        node={"id": 5},
        list_key="crew_node_list",
        changed_fields=["node_name"],
        expected={"node_name": "stale"},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "precondition_failed"
    assert result.details == {"mismatched_fields": ["node_name"]}


# ---------------------------------------------------------------------------
# CAS — non-dict base metadata does not crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_non_dict_base_metadata_does_not_crash(
    live_state_service, base_snapshot
):
    """metadata is a JSONField whose content is externally controllable via
    the REST API — a corrupted/legacy row could carry a non-dict value.
    find_mismatched_keys must treat it as empty metadata, not crash."""
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[
                {
                    "id": 5,
                    "node_name": "Crew #1",
                    "metadata": "not-a-dict-anymore",
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "position": {"x": 100, "y": 200}},
        list_key="crew_node_list",
        changed_fields=["position"],
        expected={"position": {"x": 0, "y": 0}},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "precondition_failed"
    assert result.details == {"mismatched_fields": ["position"]}


# ---------------------------------------------------------------------------
# CAS — missing base key equals expected None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_missing_base_key_equals_expected_none_applies(
    live_state_service, base_snapshot
):
    await live_state_service.seed(
        1,
        base_snapshot(crew_node_list=[{"id": 5, "node_name": "Crew #1"}]),
    )

    msg = _partial_update(
        node={"id": 5, "output_variable_path": "new.path"},
        list_key="crew_node_list",
        changed_fields=["output_variable_path"],
        expected={"output_variable_path": None},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["output_variable_path"] == "new.path"


# ---------------------------------------------------------------------------
# CAS — whole-value dict mismatch (input_map)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cas_input_map_whole_value_mismatch_rejects(
    live_state_service, base_snapshot
):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[
                {
                    "id": 5,
                    "node_name": "Crew #1",
                    "input_map": {"a": "1", "b": "2"},
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "input_map": {"a": "1"}},
        list_key="crew_node_list",
        changed_fields=["input_map"],
        # Client believes the base has no "b" key — but the base does, so
        # the whole-value compare must reject the op.
        expected={"input_map": {"a": "1"}},
    )
    result = await live_state_service.apply_op(1, msg)

    assert result.status is OpStatus.REJECTED
    assert result.reason == "precondition_failed"
    assert result.details == {"mismatched_fields": ["input_map"]}

    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["input_map"] == {"a": "1", "b": "2"}


# ---------------------------------------------------------------------------
# Protocol validator tests
# ---------------------------------------------------------------------------


def test_expected_requires_changed_fields():
    with pytest.raises(ValidationError):
        NodeUpdatedMessage(
            node={"id": 1, "node_name": "X"},
            list_key="crew_node_list",
            editor=_editor(),
            changed_fields=None,
            expected={"node_name": "Y"},
        )


def test_expected_keys_must_be_subset_of_changed_fields():
    with pytest.raises(ValidationError):
        NodeUpdatedMessage(
            node={"id": 1, "node_name": "X"},
            list_key="crew_node_list",
            editor=_editor(),
            changed_fields=["node_name"],
            expected={"node_name": "Y", "crew_id": 7},
        )


def test_expected_subset_of_changed_fields_is_valid():
    msg = NodeUpdatedMessage(
        node={"id": 1, "node_name": "X", "crew_id": 8},
        list_key="crew_node_list",
        editor=_editor(),
        changed_fields=["node_name", "crew_id"],
        expected={"node_name": "Y"},
    )
    assert msg.expected == {"node_name": "Y"}


# ---------------------------------------------------------------------------
# Consumer-level test
# ---------------------------------------------------------------------------


def _editor_payload(user) -> dict:
    return {"user_id": user.pk, "display_name": "x", "avatar_url": None}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stale_expected_nacks_sender_only_with_mismatched_fields(
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
    await comm_b.receive_json_from()  # node_created relay

    await comm_a.send_json_to(
        {
            "type": "node_updated",
            "node": {"temp_id": "n1", "node_name": "Node A Renamed"},
            "list_key": "python_node_list",
            "changed_fields": ["node_name"],
            "expected": {"node_name": "Stale Belief"},
            "op_id": "op-cas-1",
            "editor": _editor_payload(test_user),
        }
    )

    nack = await comm_a.receive_json_from()
    assert nack["type"] == "op_rejected"
    assert nack["op_id"] == "op-cas-1"
    assert nack["reason"] == "precondition_failed"
    assert nack["details"]["mismatched_fields"] == ["node_name"]

    assert await comm_b.receive_nothing(timeout=0.3)

    await comm_a.disconnect()
    await comm_b.disconnect()
