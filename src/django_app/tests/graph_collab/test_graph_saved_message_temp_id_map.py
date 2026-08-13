"""
Tests for the temp_id_map additions to GraphSavedMessage, notify_graph_saved,
and the new anotify_graph_saved async helper.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tables.graph_collab.notifications import GraphEditNotifier, anotify_graph_saved
from tables.graph_collab.protocol import GraphSavedMessage, EditorInfo


# ---------------------------------------------------------------------------
# GraphSavedMessage — temp_id_map field
# ---------------------------------------------------------------------------


class TestGraphSavedMessageTempIdMap:
    def test_defaults_to_empty_dict(self):
        """temp_id_map defaults to {} — existing callers that omit it still work."""
        msg = GraphSavedMessage(
            graph_id=1,
            new_save_version=2,
            saved_by=EditorInfo(user_id=1, display_name="A", avatar_url=None),
            saved_at="2026-01-01T00:00:00",
        )
        assert msg.temp_id_map == {}

    def test_accepts_populated_map(self):
        temp_id_map = {"tmp-abc": 42, "tmp-xyz": 99}
        msg = GraphSavedMessage(
            graph_id=1,
            new_save_version=2,
            saved_by=EditorInfo(user_id=1, display_name="A", avatar_url=None),
            saved_at="2026-01-01T00:00:00",
            temp_id_map=temp_id_map,
        )
        assert msg.temp_id_map == temp_id_map

    def test_model_dump_includes_temp_id_map(self):
        msg = GraphSavedMessage(
            graph_id=5,
            new_save_version=3,
            saved_by=EditorInfo(user_id=7, display_name="B", avatar_url=None),
            saved_at="2026-06-01T12:00:00",
            temp_id_map={"tmp-1": 100},
        )
        dumped = msg.model_dump()
        assert dumped["temp_id_map"] == {"tmp-1": 100}

    def test_model_dump_type_field_present(self):
        msg = GraphSavedMessage(
            graph_id=1,
            new_save_version=1,
            saved_by=EditorInfo(user_id=1, display_name="A", avatar_url=None),
            saved_at="2026-01-01T00:00:00",
        )
        dumped = msg.model_dump()
        assert dumped["type"] == "graph_saved"


# ---------------------------------------------------------------------------
# notify_graph_saved — passes temp_id_map into the broadcast message
# ---------------------------------------------------------------------------


def _fake_layer(mocker):
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock()
    return layer


def test_notify_graph_saved_without_temp_id_map(mocker):
    """Existing callers that omit temp_id_map still get a valid broadcast."""
    layer = _fake_layer(mocker)
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )
    user = SimpleNamespace(pk=1, display_name="Alice", email="a@b.com")

    GraphEditNotifier.notify_graph_saved(
        graph_id=10,
        new_save_version=2,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )

    layer.group_send.assert_called_once()
    _, message = layer.group_send.call_args.args
    assert message["temp_id_map"] == {}
    assert message["type"] == "graph_saved"


def test_notify_graph_saved_with_temp_id_map(mocker):
    """temp_id_map is included in the broadcast message when provided."""
    layer = _fake_layer(mocker)
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )
    user = SimpleNamespace(pk=2, display_name="Bob", email="b@c.com")

    GraphEditNotifier.notify_graph_saved(
        graph_id=20,
        new_save_version=3,
        user=user,
        saved_at="2026-06-18T10:00:00",
        temp_id_map={"tmp-xy": 55, "tmp-zz": 88},
    )

    layer.group_send.assert_called_once()
    _, message = layer.group_send.call_args.args
    assert message["temp_id_map"] == {"tmp-xy": 55, "tmp-zz": 88}


# ---------------------------------------------------------------------------
# anotify_graph_saved — async broadcast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anotify_graph_saved_calls_group_send(mocker):
    """anotify_graph_saved awaits channel_layer.group_send."""
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock()
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )
    user = SimpleNamespace(pk=3, display_name="Carol", email="c@d.com")

    await anotify_graph_saved(
        graph_id=30,
        new_save_version=5,
        user=user,
        saved_at="2026-06-18T11:00:00",
        temp_id_map={"tmp-a": 1},
    )

    layer.group_send.assert_awaited_once()
    group_name, message = layer.group_send.call_args.args
    assert group_name == "graph_edit_30"
    assert message["type"] == "graph_saved"
    assert message["graph_id"] == 30
    assert message["new_save_version"] == 5
    assert message["temp_id_map"] == {"tmp-a": 1}


@pytest.mark.asyncio
async def test_anotify_graph_saved_no_channel_layer_does_not_raise(mocker):
    """anotify_graph_saved must not raise when channel layer is absent."""
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=None,
    )
    user = SimpleNamespace(pk=4, display_name="Dave", email="d@e.com")

    await anotify_graph_saved(
        graph_id=40,
        new_save_version=1,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )


@pytest.mark.asyncio
async def test_anotify_graph_saved_swallows_group_send_error(mocker):
    """Transport errors from group_send must be swallowed, not raised."""
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock(side_effect=Exception("boom"))
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )
    user = SimpleNamespace(pk=5, display_name="Eve", email="e@f.com")

    await anotify_graph_saved(
        graph_id=50,
        new_save_version=2,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )


@pytest.mark.asyncio
async def test_anotify_graph_saved_without_temp_id_map(mocker):
    """Omitting temp_id_map produces an empty dict in the broadcast."""
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock()
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )
    user = SimpleNamespace(pk=6, display_name="Frank", email="f@g.com")

    await anotify_graph_saved(
        graph_id=60,
        new_save_version=1,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )

    layer.group_send.assert_awaited_once()
    _, message = layer.group_send.call_args.args
    assert message["temp_id_map"] == {}
