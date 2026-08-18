import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tests.fixtures import *


@pytest.mark.django_db
def test_graph_list(auth_client, graph):
    url = reverse("graphs-list")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_graph_list_empty(auth_client):
    url = reverse("graphs-list")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 0


@pytest.mark.django_db
def test_graph_post(auth_client):
    url = reverse("graphs-list")
    data = {"name": "test post", "metadata": {"data": "test data"}}

    response = auth_client.post(url, data, format="json")
    graph = Graph.objects.get(id=response.data["id"])

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["name"] == data["name"]
    assert graph.name == data["name"]
    assert response.data["metadata"] == data["metadata"]
    assert graph.metadata == data["metadata"]


@pytest.mark.django_db
def test_graph_detail(auth_client, graph):
    url = reverse("graphs-detail", args=[graph.id])

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_graph_detail_not_found(auth_client):
    url = reverse("graphs-detail", args=[999])

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_graph_put(auth_client, graph):
    url = reverse("graphs-detail", args=[graph.id])
    data = {
        "name": "test put",
        "metadata": {"data": "test data"},
        "save_version": graph.save_version,
    }

    response = auth_client.put(url, data, format="json")
    graph = Graph.objects.get(id=response.data["id"])

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == data["name"]
    assert graph.name == data["name"]
    assert response.data["metadata"] == data["metadata"]
    assert graph.metadata == data["metadata"]


@pytest.mark.django_db
def test_graph_patch(auth_client, graph):
    url = reverse("graphs-detail", args=[graph.id])
    data = {"metadata": {"data": "test data"}, "save_version": graph.save_version}

    response = auth_client.patch(url, data, format="json")
    graph = Graph.objects.get(id=response.data["id"])

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["metadata"] == data["metadata"]
    assert graph.metadata == data["metadata"]


@pytest.mark.django_db
def test_graph_delete(auth_client, graph):
    url = reverse("graphs-detail", args=[graph.id])

    response = auth_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_graph_delete_soft_delete_default_leaves_row_in_all_objects(auth_client, graph):
    """SOFT_DELETE=True (default): DELETE hides the graph from `objects` but
    keeps it in `all_objects` with `is_active=False` and `deleted_at` set."""
    graph_id = graph.id
    url = reverse("graphs-detail", args=[graph_id])

    response = auth_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not Graph.objects.filter(id=graph_id).exists()
    assert Graph.all_objects.filter(id=graph_id).exists()
    deleted_graph = Graph.all_objects.get(id=graph_id)
    assert deleted_graph.is_active is False
    assert deleted_graph.deleted_at is not None


@pytest.mark.django_db
@override_settings(SOFT_DELETE=False)
def test_graph_delete_hard_deletes_when_soft_delete_disabled(auth_client, graph):
    """SOFT_DELETE=False: DELETE removes the row entirely, even from `all_objects`."""
    graph_id = graph.id
    url = reverse("graphs-detail", args=[graph_id])

    response = auth_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not Graph.all_objects.filter(id=graph_id).exists()


@pytest.mark.django_db
def test_graph_create_with_name_of_soft_deleted_graph_succeeds(auth_client, graph):
    """The (org, name) unique constraint only applies to active rows — soft-deleting
    a graph must free up its name for reuse within the same org."""
    original_name = graph.name
    delete_url = reverse("graphs-detail", args=[graph.id])
    delete_response = auth_client.delete(delete_url)
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT

    create_url = reverse("graphs-list")
    create_response = auth_client.post(
        create_url, {"name": original_name}, format="json"
    )

    assert (
        create_response.status_code == status.HTTP_201_CREATED
    ), create_response.content
    assert create_response.data["name"] == original_name


@pytest.mark.django_db
def test_patch_graph_success_increments_save_version(auth_client, graph):
    """Correct save_version + name change → 200, name updated, save_version bumped."""
    initial_version = graph.save_version
    new_name = "patched-graph-name"

    url = reverse("graphs-detail", args=[graph.id])
    response = auth_client.patch(
        url,
        {"name": new_name, "save_version": initial_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["save_version"] == initial_version + 1
    graph.refresh_from_db()
    assert graph.name == new_name
    assert graph.save_version == initial_version + 1


@pytest.mark.django_db
def test_patch_graph_stale_version_returns_409(auth_client, graph):
    """Stale save_version → 409, name NOT updated."""
    original_name = graph.name
    Graph.objects.filter(pk=graph.pk).update(save_version=10)

    url = reverse("graphs-detail", args=[graph.id])
    response = auth_client.patch(
        url,
        {"name": "should-not-be-set", "save_version": 1},
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    graph.refresh_from_db()
    assert graph.name == original_name
