"""
Unit tests for GraphEditNotifier — message construction and defensive branches.

These tests do NOT hit the DB for the core message-shape tests (SimpleNamespace
is sufficient). The DB-using variant is also included to show a real user works.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tables.graph_collab.notifications import GraphEditNotifier


# ---------------------------------------------------------------------------
# Message content
# ---------------------------------------------------------------------------


def test_notify_graph_saved_sends_correct_message():
    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)("graph_edit_7", channel_name)

    user = SimpleNamespace(pk=42, display_name="Alice", email="alice@example.com")

    GraphEditNotifier.notify_graph_saved(
        graph_id=7,
        new_save_version=5,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )

    message = async_to_sync(channel_layer.receive)(channel_name)

    assert message["type"] == "graph_saved"
    assert message["graph_id"] == 7
    assert message["new_save_version"] == 5
    assert message["saved_by"]["user_id"] == 42
    assert message["saved_at"] == "2026-01-01T00:00:00"


@pytest.mark.django_db
def test_notify_graph_saved_with_real_user_sends_correct_message():
    from django.contrib.auth import get_user_model

    channel_layer = get_channel_layer()
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)("graph_edit_99", channel_name)

    User = get_user_model()
    user = User.objects.create_user(
        email="notif@example.com",
        password="Pass123!",
        display_name="Notif User",
    )

    GraphEditNotifier.notify_graph_saved(
        graph_id=99,
        new_save_version=3,
        user=user,
        saved_at="2026-06-01T12:00:00",
    )

    message = async_to_sync(channel_layer.receive)(channel_name)

    assert message["type"] == "graph_saved"
    assert message["graph_id"] == 99
    assert message["saved_by"]["user_id"] == user.pk


# ---------------------------------------------------------------------------
# Defensive branches
# ---------------------------------------------------------------------------


def test_send_with_no_channel_layer_does_not_raise(mocker):
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=None,
    )
    user = SimpleNamespace(pk=1, display_name="x", email="x@y.z")

    # Must not raise even though the channel layer is absent.
    GraphEditNotifier.notify_graph_saved(
        graph_id=1,
        new_save_version=1,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )


def test_send_swallows_group_send_error(mocker):
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock(side_effect=Exception("boom"))
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )

    user = SimpleNamespace(pk=2, display_name="y", email="y@z.com")

    # Must not raise — the try/except in _send swallows transport errors.
    GraphEditNotifier.notify_graph_saved(
        graph_id=2,
        new_save_version=2,
        user=user,
        saved_at="2026-01-01T00:00:00",
    )
