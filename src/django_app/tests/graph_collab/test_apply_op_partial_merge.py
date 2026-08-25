"""Tests for field-level partial node_updated + merge-only semantics.

Covers GraphLiveStateService._apply_node_merge / _apply_node_upsert.
"""

import pytest

from tables.graph_collab.graph_state_service import OpResult, OpStatus
from tables.graph_collab.protocol import (
    EditorInfo,
    EntryDeleteRef,
    NodeCreatedMessage,
    NodesDeletedMessage,
    NodeUpdatedMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _partial_update(
    node: dict,
    list_key: str,
    changed_fields: list[str],
    editor: EditorInfo,
    op_id: str | None = None,
) -> NodeUpdatedMessage:
    return NodeUpdatedMessage(
        node=node,
        list_key=list_key,
        editor=editor,
        changed_fields=changed_fields,
        op_id=op_id,
    )


# ---------------------------------------------------------------------------
# Core merge behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_only_partial_update_preserves_crew_id(
    live_state_service, base_snapshot, editor
):
    """FE always sends the whole nested `metadata` dict as one changed field
    (never a bare top-level `position`) — see buildNodeBackendPayload /
    toNodeMetadata. `merge_entry` sub-merges `metadata` (tested directly in
    test_entry_merge.py); this covers the same behavior through the real
    apply_op integration path."""
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[
                {
                    "id": 5,
                    "crew_id": 7,
                    "node_name": "Crew #1",
                    "metadata": {"position": {"x": 0, "y": 0}},
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "metadata": {"position": {"x": 100, "y": 200}}},
        list_key="crew_node_list",
        changed_fields=["metadata"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["crew_id"] == 7
    assert entry["node_name"] == "Crew #1"
    assert entry["metadata"]["position"] == {"x": 100, "y": 200}


@pytest.mark.asyncio
async def test_declared_python_code_replaced_whole(
    live_state_service, base_snapshot, editor
):
    """A partial op declaring 'python_code' as changed replaces it WHOLE
    (merge policy): the FE always sends the complete value of a
    declared-changed field, so a partial python_code payload here means the
    caller intentionally dropped 'entrypoint' and 'libraries' — they must not
    be resurrected from the base entry."""
    await live_state_service.seed(
        1,
        base_snapshot(
            python_node_list=[
                {
                    "id": 10,
                    "node_name": "Python-Node #1",
                    "python_code": {
                        "code": "def main(): return 0",
                        "entrypoint": "main",
                        "libraries": ["requests"],
                        "global_kwargs": {},
                    },
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 10, "python_code": {"code": "def main(): return 1"}},
        list_key="python_node_list",
        changed_fields=["python_code"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["python_node_list"][0]
    assert entry["python_code"] == {"code": "def main(): return 1"}


@pytest.mark.asyncio
async def test_input_map_key_deletion_propagates_through_apply_op(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[
                {
                    "id": 20,
                    "node_name": "Crew #1",
                    "input_map": {"a": "1", "b": "2"},
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 20, "input_map": {"a": "1"}},
        list_key="crew_node_list",
        changed_fields=["input_map"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["input_map"] == {"a": "1"}
    assert "b" not in entry["input_map"]


@pytest.mark.asyncio
async def test_metadata_partial_preserves_node_number_set_by_another_op(
    live_state_service, base_snapshot, editor
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
                        "nodeNumber": 7,
                        "color": "#123",
                    },
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 5, "metadata": {"position": {"x": 50, "y": 60}}},
        list_key="crew_node_list",
        changed_fields=["metadata"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["metadata"]["position"] == {"x": 50, "y": 60}
    assert entry["metadata"]["nodeNumber"] == 7
    assert entry["metadata"]["color"] == "#123"


@pytest.mark.asyncio
async def test_condition_groups_present_in_overlay_replaced_whole(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1,
        base_snapshot(
            decision_table_node_list=[
                {
                    "id": 3,
                    "condition_groups": [
                        {"id": 1, "label": "a"},
                        {"id": 2, "label": "b"},
                    ],
                    "default_next_node_id": None,
                }
            ]
        ),
    )

    msg = _partial_update(
        node={"id": 3, "condition_groups": [{"id": 9, "label": "z"}]},
        list_key="decision_table_node_list",
        changed_fields=["condition_groups"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["decision_table_node_list"][0]
    assert entry["condition_groups"] == [{"id": 9, "label": "z"}]
    assert entry["default_next_node_id"] is None


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_target_not_found_rejects_without_mutating_snapshot(
    live_state_service, base_snapshot, editor
):
    snapshot = base_snapshot(python_node_list=[{"id": 1, "node_name": "Existing"}])
    await live_state_service.seed(1, snapshot)
    revision_before = live_state_service.current_revision(1)

    msg = _partial_update(
        node={"id": 999, "node_name": "Ghost"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.REJECTED, "target_not_found", relay=False)
    after = await live_state_service.get_snapshot(1)
    assert after["python_node_list"] == [{"id": 1, "node_name": "Existing"}]
    assert live_state_service.current_revision(1) == revision_before


@pytest.mark.asyncio
async def test_no_snapshot_rejects_with_relay_false(live_state_service, editor):
    msg = _partial_update(
        node={"id": 1, "node_name": "X"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.REJECTED, "no_snapshot", relay=False)


@pytest.mark.asyncio
async def test_unknown_list_key_rejects_with_relay_false(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(1, base_snapshot())
    revision_before = live_state_service.current_revision(1)

    msg = _partial_update(
        node={"id": 1, "node_name": "X"},
        list_key="not_a_real_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.REJECTED, "unknown_list_key", relay=False)
    assert live_state_service.current_revision(1) == revision_before


@pytest.mark.asyncio
async def test_partial_update_after_real_id_delete_is_rejected_no_resurrect(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 10, "node_name": "Doomed"}])
    )

    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="python_node_list", id=10)],
        editor=editor,
    )
    await live_state_service.apply_op(1, delete_msg)
    snapshot_after_delete = await live_state_service.get_snapshot(1)
    assert snapshot_after_delete["python_node_list"] == []
    assert snapshot_after_delete["deleted"]["python_node_ids"] == [10]

    msg = _partial_update(
        node={"id": 10, "node_name": "Resurrect me"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.REJECTED, "target_not_found", relay=False)
    after = await live_state_service.get_snapshot(1)
    assert after["python_node_list"] == []
    assert after["deleted"]["python_node_ids"] == [10]


@pytest.mark.asyncio
async def test_temp_deleted_node_then_partial_update_by_temp_id_is_rejected(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(1, base_snapshot())

    create_msg = NodeCreatedMessage(
        node={"temp_id": "temp-1", "node_name": "New Node"},
        list_key="python_node_list",
        editor=editor,
    )
    await live_state_service.apply_op(1, create_msg)
    created = (await live_state_service.get_snapshot(1))["python_node_list"]
    assert len(created) == 1
    assert created[0]["temp_id"] == "temp-1"
    assert created[0]["node_name"] == "New Node"

    delete_msg = NodesDeletedMessage(
        refs=[EntryDeleteRef(list_key="python_node_list", temp_id="temp-1")],
        editor=editor,
    )
    await live_state_service.apply_op(1, delete_msg)
    assert (await live_state_service.get_snapshot(1))["python_node_list"] == []

    msg = _partial_update(
        node={"temp_id": "temp-1", "node_name": "Zombie"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.REJECTED, "target_not_found", relay=False)
    assert (await live_state_service.get_snapshot(1))["python_node_list"] == []


# ---------------------------------------------------------------------------
# temp_id resolution after remap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_update_by_resolved_temp_id_applies_onto_real_id_entry(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 55, "node_name": "Real Node"}])
    )
    await live_state_service.record_resolved_temp_ids(1, {"tmp-99": 55})

    msg = _partial_update(
        node={"temp_id": "tmp-99", "node_name": "Renamed"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["python_node_list"][0]
    assert entry["id"] == 55
    assert entry["node_name"] == "Renamed"
    assert "temp_id" not in entry


@pytest.mark.asyncio
async def test_partial_update_with_both_id_and_stale_temp_id_drops_temp_id(
    live_state_service, base_snapshot, editor
):
    """A persisted entry must never carry both id and temp_id — if the op
    carries a stale temp_id alongside a matching real id, the merge must not
    attach that temp_id to the persisted entry."""
    await live_state_service.seed(
        1, base_snapshot(python_node_list=[{"id": 55, "node_name": "Real Node"}])
    )

    msg = _partial_update(
        node={"id": 55, "temp_id": "stale-temp", "node_name": "Renamed"},
        list_key="python_node_list",
        changed_fields=["node_name"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["python_node_list"][0]
    assert entry["id"] == 55
    assert entry["node_name"] == "Renamed"
    assert "temp_id" not in entry


# ---------------------------------------------------------------------------
# Singleton lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_singleton_start_node_partial_with_mismatched_temp_id_merges_into_entry(
    live_state_service, base_snapshot, editor
):
    """'variables' is a user-key dict field (merge policy): the FE always
    sends its complete value, so the overlay here — a complete replacement
    value with no 'persistent' key — must replace 'variables' whole rather
    than sub-merging and resurrecting 'persistent'."""
    await live_state_service.seed(
        1,
        base_snapshot(
            start_node_list=[
                {
                    "id": 8,
                    "node_name": "Start",
                    "variables": {"variables": {"a": 1}, "persistent": {}},
                }
            ]
        ),
    )

    msg = _partial_update(
        node={
            "temp_id": "mismatched-temp",
            "variables": {"variables": {"a": 2}, "persistent": {}},
        },
        list_key="start_node_list",
        changed_fields=["variables"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entries = (await live_state_service.get_snapshot(1))["start_node_list"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == 8
    assert "temp_id" not in entry
    assert entry["variables"] == {"variables": {"a": 2}, "persistent": {}}


# ---------------------------------------------------------------------------
# Masking behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mask_name_absent_from_node_is_ignored_and_undeclared_keys_dropped(
    live_state_service, base_snapshot, editor
):
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[{"id": 5, "crew_id": 7, "node_name": "Old Name"}]
        ),
    )

    msg = _partial_update(
        # "ghost_field" is declared changed but absent from node -> ignored.
        # "extra_field" is present on node but NOT declared changed -> dropped.
        node={"id": 5, "node_name": "New Name", "extra_field": "should not survive"},
        list_key="crew_node_list",
        changed_fields=["node_name", "ghost_field"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    entry = (await live_state_service.get_snapshot(1))["crew_node_list"][0]
    assert entry["node_name"] == "New Name"
    assert entry["crew_id"] == 7
    assert "extra_field" not in entry
    assert "ghost_field" not in entry


# ---------------------------------------------------------------------------
# Legacy back-compat pin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_node_updated_without_changed_fields_upserts_and_resurrects(
    live_state_service, base_snapshot, empty_deleted, editor
):
    """Documents back-compat: a NodeUpdatedMessage with changed_fields=None keeps
    the pre-merge-policy wholesale-replace semantics — append-on-miss and
    delete-accumulator resurrect both still apply."""
    await live_state_service.seed(
        1,
        base_snapshot(
            crew_node_list=[],
            deleted={**empty_deleted(), "crew_node_ids": [42]},
        ),
    )

    msg = NodeUpdatedMessage(
        node={"id": 42, "crew_id": 9, "node_name": "Resurrected"},
        list_key="crew_node_list",
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg)

    assert result == OpResult(OpStatus.APPLIED)
    snapshot = await live_state_service.get_snapshot(1)
    assert len(snapshot["crew_node_list"]) == 1
    assert snapshot["crew_node_list"][0]["id"] == 42
    assert snapshot["crew_node_list"][0]["crew_id"] == 9
    assert 42 not in snapshot["deleted"]["crew_node_ids"]
