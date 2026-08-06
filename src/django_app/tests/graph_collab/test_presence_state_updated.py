"""
Tests for the presence_state_updated feature:
- GraphPresenceService.update_editor_for_user
- GraphEditNotifier.notify_profile_updated
- GraphEditConsumer.presence_state_updated channel-layer handler
- View-level trigger: profile PATCH / avatar POST / avatar DELETE
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from tables.graph_collab.notifications import GraphEditNotifier
from tables.graph_collab.presence_service import GraphPresenceService, presence_service

from tests.graph_collab.conftest import _editor

# ---------------------------------------------------------------------------
# GraphPresenceService.update_editor_for_user
# ---------------------------------------------------------------------------


def test_update_editor_replaces_across_multiple_graphs(presence_service):
    old = _editor(user_id=1, name="Old Name")
    presence_service.add(graph_id=10, channel_name="ch-a", editor=old)
    presence_service.add(graph_id=20, channel_name="ch-b", editor=old)
    # A different user also present in graph 20 — should be untouched.
    other = _editor(user_id=99, name="Other")
    presence_service.add(graph_id=20, channel_name="ch-c", editor=other)

    updated = _editor(user_id=1, name="New Name")
    affected = presence_service.update_editor_for_user(user_id=1, editor=updated)

    assert sorted(affected) == [10, 20]
    assert presence_service._store[10]["ch-a"].display_name == "New Name"
    assert presence_service._store[20]["ch-b"].display_name == "New Name"
    # Other user unchanged.
    assert presence_service._store[20]["ch-c"].display_name == "Other"


def test_update_editor_returns_empty_when_user_not_present(presence_service):
    presence_service.add(graph_id=10, channel_name="ch-a", editor=_editor(user_id=99))

    affected = presence_service.update_editor_for_user(
        user_id=1, editor=_editor(user_id=1)
    )

    assert affected == []


def test_update_editor_returns_empty_when_store_is_empty(presence_service):
    affected = presence_service.update_editor_for_user(
        user_id=1, editor=_editor(user_id=1)
    )
    assert affected == []


# ---------------------------------------------------------------------------
# GraphEditNotifier.notify_profile_updated
# ---------------------------------------------------------------------------


def test_notify_profile_updated_broadcasts_to_each_affected_graph():
    channel_layer = get_channel_layer()
    ch1 = async_to_sync(channel_layer.new_channel)()
    ch2 = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)("graph_edit_1", ch1)
    async_to_sync(channel_layer.group_add)("graph_edit_2", ch2)

    editor = _editor(user_id=5, name="Pavlo")
    presence_service.add(graph_id=1, channel_name="ch-1", editor=editor)
    presence_service.add(graph_id=2, channel_name="ch-2", editor=editor)

    user = SimpleNamespace(
        pk=5, display_name="Pavlo Updated", email="p@e.com", avatar=None
    )
    GraphEditNotifier.notify_profile_updated(user)

    msg1 = async_to_sync(channel_layer.receive)(ch1)
    msg2 = async_to_sync(channel_layer.receive)(ch2)

    assert msg1["type"] == "presence_state_updated"
    assert msg1["editor"]["user_id"] == 5
    assert msg1["editor"]["display_name"] == "Pavlo Updated"

    assert msg2["type"] == "presence_state_updated"
    assert msg2["editor"]["user_id"] == 5
    assert msg2["editor"]["display_name"] == "Pavlo Updated"


def test_notify_profile_updated_is_noop_when_user_not_present(mocker):
    send_spy = mocker.spy(GraphEditNotifier, "_send")

    user = SimpleNamespace(pk=5, display_name="Ghost", email="g@e.com", avatar=None)
    GraphEditNotifier.notify_profile_updated(user)

    send_spy.assert_not_called()


def test_notify_profile_updated_does_not_raise_when_channel_layer_is_none(mocker):
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=None,
    )

    editor = _editor(user_id=7)

    presence_service.add(graph_id=1, channel_name="ch-x", editor=editor)

    user = SimpleNamespace(pk=7, display_name="User7", email="u@e.com", avatar=None)
    # Must not raise even without a channel layer.
    GraphEditNotifier.notify_profile_updated(user)


def test_notify_profile_updated_does_not_raise_when_group_send_raises(mocker):
    layer = mocker.MagicMock()
    layer.group_send = AsyncMock(side_effect=Exception("transport failure"))
    mocker.patch(
        "tables.graph_collab.notifications.get_channel_layer",
        return_value=layer,
    )

    editor = _editor(user_id=8)

    presence_service.add(graph_id=1, channel_name="ch-y", editor=editor)

    user = SimpleNamespace(pk=8, display_name="User8", email="u8@e.com", avatar=None)
    # _send swallows exceptions — must not propagate.
    GraphEditNotifier.notify_profile_updated(user)


# ---------------------------------------------------------------------------
# Consumer channel-layer handler: presence_state_updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_presence_state_updated_handler_forwards_event_to_client(
    test_graph, test_user, make_communicator
):
    from asgiref.sync import sync_to_async

    communicator = make_communicator(test_graph.pk, test_user)
    await communicator.connect()

    # Drain the initial presence_state + graph_state + user_joined messages.
    await communicator.receive_json_from()
    await communicator.receive_json_from()
    await communicator.receive_json_from()

    event = {
        "type": "presence_state_updated",
        "editor": {
            "user_id": test_user.pk,
            "display_name": "Updated",
            "avatar_url": None,
        },
    }
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    group_name = f"graph_edit_{test_graph.pk}"
    await layer.group_send(group_name, event)

    msg = await communicator.receive_json_from()
    assert msg["type"] == "presence_state_updated"
    assert msg["editor"]["user_id"] == test_user.pk
    assert msg["editor"]["display_name"] == "Updated"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# View-level trigger: assert notify_profile_updated is called
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_patch_display_name_triggers_notify(auth_client, regular_user, mocker):
    notify_mock = mocker.patch(
        "tables.views.user_profile_views.GraphEditNotifier.notify_profile_updated"
    )
    from django.urls import reverse
    from rest_framework import status

    url = reverse("profile")
    response = auth_client.patch(url, {"display_name": "New Name"}, format="json")
    assert response.status_code == status.HTTP_200_OK
    notify_mock.assert_called_once()


@pytest.mark.django_db
def test_profile_patch_without_display_name_does_not_trigger_notify(
    auth_client, regular_user, mocker
):
    """PATCH that sends no display_name field should not trigger a broadcast."""
    notify_mock = mocker.patch(
        "tables.views.user_profile_views.GraphEditNotifier.notify_profile_updated"
    )
    from django.urls import reverse
    from rest_framework import status

    url = reverse("profile")
    # Send an empty patch — no fields to update.
    response = auth_client.patch(url, {}, format="json")
    assert response.status_code == status.HTTP_200_OK
    notify_mock.assert_not_called()


@pytest.mark.django_db
def test_avatar_delete_triggers_notify(auth_client, regular_user, mocker):
    notify_mock = mocker.patch(
        "tables.views.user_profile_views.GraphEditNotifier.notify_profile_updated"
    )
    from django.urls import reverse
    from rest_framework import status

    url = reverse("profile_avatar")
    response = auth_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT
    notify_mock.assert_called_once()


@pytest.mark.django_db
def test_avatar_post_triggers_notify(auth_client, regular_user, mocker):
    notify_mock = mocker.patch(
        "tables.views.user_profile_views.GraphEditNotifier.notify_profile_updated"
    )
    mocker.patch(
        "tables.views.user_profile_views.UserProfileService.update_avatar",
        return_value=regular_user,
    )
    mocker.patch(
        "tables.views.user_profile_views.UserProfileService.get_profile",
        return_value=regular_user,
    )
    mocker.patch(
        "tables.views.user_profile_views.UserValidationService.validate_avatar_upload",
        return_value=mocker.MagicMock(),
    )
    from django.urls import reverse
    from rest_framework import status

    url = reverse("profile_avatar")
    response = auth_client.post(url, {}, format="multipart")
    assert response.status_code == status.HTTP_200_OK
    notify_mock.assert_called_once()
