"""Tests for the privileged-nested-field pinning added to apply_op:
a non-superadmin WS caller must never be able to
smuggle an arbitrary ngrok_webhook_config into the live snapshot, while a
superadmin's writes (including explicit clears) pass through untouched, and
callers that legitimately resend the current value unchanged (resize,
auto-arrange, reconnect-resync) are never falsely reported as "pinned".

Covers GraphLiveStateService.apply_op / _apply_node_upsert / _apply_node_merge
via _pin_privileged_fields — see graph_state_service.py and
constants.PRIVILEGED_NESTED_FIELDS.
"""

import pytest

from tables.graph_collab.graph_state_service import OpStatus
from tables.graph_collab.protocol import NodeCreatedMessage, NodeUpdatedMessage


LIST_KEYS = ["webhook_trigger_node_list", "telegram_trigger_node_list"]


def _created(node: dict, list_key: str, editor) -> NodeCreatedMessage:
    return NodeCreatedMessage(node=node, list_key=list_key, editor=editor)


def _merge_update(
    node: dict, list_key: str, changed_fields: list[str], editor
) -> NodeUpdatedMessage:
    return NodeUpdatedMessage(
        node=node, list_key=list_key, editor=editor, changed_fields=changed_fields
    )


def _legacy_update(node: dict, list_key: str, editor) -> NodeUpdatedMessage:
    return NodeUpdatedMessage(
        node=node, list_key=list_key, editor=editor, changed_fields=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_merge_op_non_superadmin_different_ngrok_is_pinned(
    live_state_service, base_snapshot, editor, list_key
):
    await live_state_service.seed(
        1,
        base_snapshot(
            **{
                list_key: [
                    {
                        "id": 5,
                        "node_name": "Trigger",
                        "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 1},
                    }
                ]
            }
        ),
    )

    msg = _merge_update(
        node={"id": 5, "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 99}},
        list_key=list_key,
        changed_fields=["webhook_trigger"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg, is_superadmin=False)

    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_merge_op_non_superadmin_equal_ngrok_not_reported(
    live_state_service, base_snapshot, editor, list_key
):
    """Regression guard: resize/auto-arrange/reconnect-resync legitimately
    resend the unchanged current value — this must apply cleanly and leave
    the value untouched."""
    await live_state_service.seed(
        1,
        base_snapshot(
            **{
                list_key: [
                    {
                        "id": 5,
                        "node_name": "Trigger",
                        "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 1},
                    }
                ]
            }
        ),
    )

    msg = _merge_update(
        node={"id": 5, "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 1}},
        list_key=list_key,
        changed_fields=["webhook_trigger"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg, is_superadmin=False)

    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_merge_op_overlay_omitting_key_survives_whole_key_replace(
    live_state_service, base_snapshot, editor, list_key
):
    """merge_entry whole-key-replaces `webhook_trigger` — an overlay that
    carries the nested key but omits ngrok_webhook_config must not silently
    drop the existing config."""
    await live_state_service.seed(
        1,
        base_snapshot(
            **{
                list_key: [
                    {
                        "id": 5,
                        "node_name": "Trigger",
                        "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 1},
                    }
                ]
            }
        ),
    )

    msg = _merge_update(
        node={"id": 5, "webhook_trigger": {"path": "xyz"}},
        list_key=list_key,
        changed_fields=["webhook_trigger"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg, is_superadmin=False)

    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] == 1
    assert entry["webhook_trigger"]["path"] == "xyz"


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_legacy_upsert_on_existing_node_preserves_current_value(
    live_state_service, base_snapshot, editor, list_key
):
    """Legacy no-changed_fields path (_apply_node_upsert) — a non-superadmin
    caller can't overwrite ngrok_webhook_config on an existing node either."""
    await live_state_service.seed(
        1,
        base_snapshot(
            **{
                list_key: [
                    {
                        "id": 5,
                        "node_name": "Trigger",
                        "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 1},
                    }
                ]
            }
        ),
    )

    msg = _legacy_update(
        node={
            "id": 5,
            "node_name": "Trigger renamed",
            "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 99},
        },
        list_key=list_key,
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg, is_superadmin=False)

    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] == 1
    assert entry["node_name"] == "Trigger renamed"


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_node_created_by_non_superadmin_stores_none(
    live_state_service, base_snapshot, editor, list_key
):
    await live_state_service.seed(1, base_snapshot())

    msg = _created(
        node={
            "temp_id": "temp-1",
            "node_name": "New Trigger",
            "webhook_trigger": {"path": "new", "ngrok_webhook_config": 42},
        },
        list_key=list_key,
        editor=editor,
    )
    result = await live_state_service.apply_op(1, msg, is_superadmin=False)

    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("list_key", LIST_KEYS)
async def test_superadmin_set_and_clear_both_persist(
    live_state_service, base_snapshot, editor, list_key
):
    await live_state_service.seed(
        1,
        base_snapshot(
            **{
                list_key: [
                    {
                        "id": 5,
                        "node_name": "Trigger",
                        "webhook_trigger": {
                            "path": "abc",
                            "ngrok_webhook_config": None,
                        },
                    }
                ]
            }
        ),
    )

    set_msg = _merge_update(
        node={"id": 5, "webhook_trigger": {"path": "abc", "ngrok_webhook_config": 7}},
        list_key=list_key,
        changed_fields=["webhook_trigger"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, set_msg, is_superadmin=True)
    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] == 7

    clear_msg = _merge_update(
        node={
            "id": 5,
            "webhook_trigger": {"path": "abc", "ngrok_webhook_config": None},
        },
        list_key=list_key,
        changed_fields=["webhook_trigger"],
        editor=editor,
    )
    result = await live_state_service.apply_op(1, clear_msg, is_superadmin=True)
    assert result.status == OpStatus.APPLIED
    assert result.relay is True
    entry = (await live_state_service.get_snapshot(1))[list_key][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] is None
