"""
Integration tests: verify that a graph_saved broadcast is emitted on every
mutation path that calls GraphEditNotifier.notify_graph_saved.
"""

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse
from rest_framework import status

from tables.graph_collab.notifications import GraphEditNotifier
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subscribe_to_graph(channel_layer, graph_id: int) -> str:
    """Add a fresh channel to the graph group and return the channel name."""
    channel_name = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(f"graph_edit_{graph_id}", channel_name)
    return channel_name


def _assert_graph_saved(
    channel_layer, channel_name: str, graph_id: int, user_id: int, expected_version: int
) -> None:
    message = async_to_sync(channel_layer.receive)(channel_name)
    assert message["type"] == "graph_saved"
    assert message["graph_id"] == graph_id
    assert message["saved_by"]["user_id"] == user_id
    assert message["new_save_version"] == expected_version


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


@pytest.mark.django_db
def test_restore_broadcasts_graph_saved(auth_client, regular_user, graph):
    version = GraphVersioningService().save_version(graph, name="v1")

    channel_layer = get_channel_layer()
    channel_name = _subscribe_to_graph(channel_layer, graph.id)

    url = reverse("graph-versions-restore", args=[version.id])
    payload = {"save_version": graph.save_version}
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    result_graph_id = response.data["graph_id"]
    assert result_graph_id == graph.id

    expected_version = Graph.objects.get(pk=graph.id).save_version
    _assert_graph_saved(
        channel_layer, channel_name, graph.id, regular_user.pk, expected_version
    )


@pytest.mark.django_db
def test_save_flow_version_conflict_does_not_broadcast(auth_client, graph, mocker):
    send_spy = mocker.spy(GraphEditNotifier, "_send")

    url = reverse("graphs-save-flow", args=[graph.id])
    payload = {
        "save_version": graph.save_version + 999,
    }
    response = auth_client.post(url, payload, format="json")
    assert response.status_code == status.HTTP_409_CONFLICT, response.content

    send_spy.assert_not_called()
