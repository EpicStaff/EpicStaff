"""
Integration tests verifying graph-group broadcasts on save/restore paths:
a `graph_saved` message on every mutation that calls
GraphEditNotifier.notify_graph_saved, and a `graph_state` message when a
version restore targets a graph with a live collaboration session. Also
covers the socket-delivery leg of `graph_saved` — a connected WebSocket
receiving the message pushed by GraphEditNotifier directly.
"""

import asyncio

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.notifications import GraphEditNotifier
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subscribe_to_graph(channel_layer, graph_id: int) -> str:
    """Add a fresh channel to the graph group and return the channel name."""
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(f"graph_edit_{graph_id}", channel_name)
    return channel_name


def _receive_broadcast(channel_layer, channel_name: str, timeout: float = 2.0) -> dict:
    async def _wait_for_message() -> dict:
        return await asyncio.wait_for(
            channel_layer.receive(channel_name), timeout=timeout
        )

    try:
        return async_to_sync(_wait_for_message)()
    except asyncio.TimeoutError:
        raise AssertionError("expected a broadcast to the graph group but none arrived")


def _assert_graph_saved(
    channel_layer, channel_name: str, graph_id: int, user_id: int, expected_version: int
) -> None:
    message = _receive_broadcast(channel_layer, channel_name)
    assert message["type"] == "graph_saved"
    assert message["graph_id"] == graph_id
    assert message["saved_by"]["user_id"] == user_id
    assert message["new_save_version"] == expected_version


def _assert_nothing_broadcast(
    channel_layer, channel_name: str, timeout: float = 0.3
) -> None:
    async def _wait_for_message() -> bool:
        try:
            await asyncio.wait_for(channel_layer.receive(channel_name), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    received_something = async_to_sync(_wait_for_message)()
    assert not received_something, "expected no broadcast to the graph group"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_put_broadcasts_graph_saved(auth_client, regular_user, graph):
    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graphs-detail", args=[graph.id])

    payload = {
        "name": "renamed graph",
        "save_version": graph.save_version,
    }
    response = auth_client.put(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    expected_version = Graph.objects.get(pk=graph.id).save_version
    _assert_graph_saved(
        channel_layer, channel_name, graph.id, regular_user.pk, expected_version
    )


@pytest.mark.django_db
def test_patch_broadcasts_graph_saved(auth_client, regular_user, graph):
    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graphs-detail", args=[graph.id])
    payload = {
        "name": "renamed via patch",
        "save_version": graph.save_version,
    }
    response = auth_client.patch(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    expected_version = Graph.objects.get(pk=graph.id).save_version
    _assert_graph_saved(
        channel_layer, channel_name, graph.id, regular_user.pk, expected_version
    )


@pytest.mark.django_db
def test_save_flow_broadcasts_graph_saved(auth_client, regular_user, graph):
    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graphs-save-flow", args=[graph.id])
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "graph": graph.id,
                "python_code": {
                    "code": "def main(): return 1",
                    "entrypoint": "main",
                    "libraries": [],
                },
            }
        ],
    }
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    expected_version = Graph.objects.get(pk=graph.id).save_version
    _assert_graph_saved(
        channel_layer, channel_name, graph.id, regular_user.pk, expected_version
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_graph_saved_pushed_via_notifier(
    test_graph, test_user, make_communicator
):
    communicator = make_communicator(test_graph.pk, test_user)
    await communicator.connect()

    # Drain presence_state, user_joined, and graph_state (DB-seeded).
    await communicator.receive_json_from()
    await communicator.receive_json_from()
    await communicator.receive_json_from()

    await sync_to_async(GraphEditNotifier.notify_graph_saved)(
        graph_id=test_graph.pk,
        new_save_version=5,
        user=test_user,
        saved_at=timezone.now().isoformat(),
    )

    msg = await communicator.receive_json_from()
    assert msg["type"] == "graph_saved"
    assert msg["graph_id"] == test_graph.pk
    assert msg["new_save_version"] == 5
    assert msg["saved_by"]["user_id"] == test_user.pk

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
def test_restore_broadcasts_graph_state_to_live_session(
    auth_client, regular_user, graph, base_snapshot
):
    version = GraphVersioningService().save_version(graph, name="v1")

    # Restore only broadcasts when a live collaboration session exists for the
    # graph (GraphVersionViewSet.restore gates on has_live_session); seed one
    # directly instead of opening a real WebSocket.
    async_to_sync(graph_state_service.seed)(
        graph.id, base_snapshot(save_version=graph.save_version)
    )
    assert async_to_sync(graph_state_service.get_snapshot)(graph.id) is not None

    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graph-versions-restore", args=[version.id])
    payload = {"save_version": graph.save_version}
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    expected_version = Graph.objects.get(pk=graph.id).save_version
    message = _receive_broadcast(channel_layer, channel_name)
    assert message["type"] == "graph_state"
    assert message["new_save_version"] == expected_version
    assert message["version_name"] == "v1"
    assert message["restored_by"]["user_id"] == regular_user.pk


@pytest.mark.django_db
def test_save_flow_version_conflict_does_not_broadcast(auth_client, graph):
    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graphs-save-flow", args=[graph.id])
    payload = {
        "save_version": graph.save_version + 999,
    }
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_409_CONFLICT, response.content

    _assert_nothing_broadcast(channel_layer, channel_name)
