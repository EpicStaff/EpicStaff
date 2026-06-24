"""Layer 4 tests: GraphVersionViewSet (HTTP API)."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph, GraphVersion
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def make_graph_version(auth_client, graph):
    """Create a GraphVersion through the API and return response.data.

    Defaults to the `graph` fixture; pass `graph_obj=` to bind to a different
    graph. The fixture asserts 201 — if creation fails, pytest reports a
    setup error rather than a test failure.
    """

    def _make(*, name="test-version", description="", graph_obj=None):
        target = graph_obj or graph
        payload = {"graph_id": target.id, "name": name}
        if description:
            payload["description"] = description
        response = auth_client.post(
            reverse("graph-versions-list"), payload, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.data

    return _make


# ---------------------------------------------------------------------------
# Group A: list / create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_version_returns_201_with_serialized_fields(auth_client, graph):
    url = reverse("graph-versions-list")
    payload = {"graph_id": graph.id, "name": "v1", "description": "first"}

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["id"] is not None
    assert response.data["graph_id"] == graph.id
    assert response.data["name"] == "v1"
    assert response.data["description"] == "first"
    assert response.data["created_at"] is not None


@pytest.mark.django_db
def test_create_version_persists_row_in_db(auth_client, graph):
    url = reverse("graph-versions-list")
    payload = {"graph_id": graph.id, "name": "persisted"}

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    version = GraphVersion.objects.get(id=response.data["id"])
    assert version.name == "persisted"
    assert version.graph_id == graph.id


@pytest.mark.django_db
def test_create_version_without_name_returns_400(auth_client, graph):
    url = reverse("graph-versions-list")
    payload = {"graph_id": graph.id}

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


@pytest.mark.django_db
def test_create_version_with_nonexistent_graph_returns_400(auth_client):
    url = reverse("graph-versions-list")
    payload = {"graph_id": 99999, "name": "orphan"}

    response = auth_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


@pytest.mark.django_db
def test_list_versions_filters_by_graph_id(auth_client, graph, make_graph_version):
    other_graph = Graph.objects.create(name="other")

    make_graph_version(name="v-main")
    make_graph_version(name="v-other", graph_obj=other_graph)

    list_url = reverse("graph-versions-list")
    response = auth_client.get(list_url + f"?graph_id={graph.id}")

    assert response.status_code == status.HTTP_200_OK, response.content
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["graph_id"] == graph.id


# ---------------------------------------------------------------------------
# Group B: update + soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_version_updates_name_and_description(auth_client, make_graph_version):
    version = make_graph_version(name="original", description="old desc")
    version_id = version["id"]

    detail_url = reverse("graph-versions-detail", args=[version_id])
    patch_response = auth_client.patch(
        detail_url, {"name": "renamed", "description": "new desc"}, format="json"
    )

    assert patch_response.status_code == status.HTTP_200_OK, patch_response.content
    assert patch_response.data["name"] == "renamed"
    assert patch_response.data["description"] == "new desc"
    version = GraphVersion.objects.get(id=version_id)
    assert version.name == "renamed"
    assert version.description == "new desc"


@pytest.mark.django_db
def test_delete_version_soft_deletes(auth_client, make_graph_version):
    version = make_graph_version(name="to-delete")
    version_id = version["id"]

    detail_url = reverse("graph-versions-detail", args=[version_id])
    delete_response = auth_client.delete(detail_url)

    assert (
        delete_response.status_code == status.HTTP_204_NO_CONTENT
    ), delete_response.content

    get_response = auth_client.get(detail_url)
    assert get_response.status_code == status.HTTP_404_NOT_FOUND, get_response.content

    assert not GraphVersion.objects.filter(id=version_id).exists()
    assert GraphVersion.all_objects.filter(id=version_id).exists()
    assert GraphVersion.all_objects.get(id=version_id).deleted_at is not None


@pytest.mark.django_db
def test_all_endpoint_includes_soft_deleted(auth_client, make_graph_version):
    version = make_graph_version(name="will-be-deleted")
    version_id = version["id"]

    detail_url = reverse("graph-versions-detail", args=[version_id])
    auth_client.delete(detail_url)

    all_url = reverse("graph-versions-all")
    all_response = auth_client.get(all_url)

    assert all_response.status_code == status.HTTP_200_OK, all_response.content
    ids_in_response = [item["id"] for item in all_response.data["results"]]
    assert version_id in ids_in_response


# ---------------------------------------------------------------------------
# Group C: restore action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_returns_200_with_response_dict_structure(
    auth_client, graph, make_graph_version
):
    version = make_graph_version(name="snap")
    version_id = version["id"]

    graph.refresh_from_db()
    restore_url = reverse("graph-versions-restore", args=[version_id])
    response = auth_client.post(
        restore_url,
        {"save_version": graph.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["restored"] is True
    assert response.data["graph_id"] == graph.id
    assert isinstance(response.data["warnings"], list)
    assert response.data["auto_backup_version_id"] is None


@pytest.mark.django_db
def test_restore_with_backup_true_creates_backup_version(
    auth_client, graph, make_graph_version
):
    version = make_graph_version(name="snap-for-backup")
    version_id = version["id"]

    graph.refresh_from_db()
    restore_url = reverse("graph-versions-restore", args=[version_id])
    response = auth_client.post(
        restore_url + "?backup=true",
        {"save_version": graph.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    auto_backup_id = response.data["auto_backup_version_id"]
    assert auto_backup_id is not None
    assert GraphVersion.objects.filter(id=auto_backup_id).exists()
    backup = GraphVersion.objects.get(id=auto_backup_id)
    assert backup.name.startswith("Before restore to '")


# ---------------------------------------------------------------------------
# Group D: 404 edge cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_nonexistent_version_returns_404(auth_client):
    restore_url = reverse("graph-versions-restore", args=[99999])

    response = auth_client.post(restore_url, {"save_version": 1}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_detail_nonexistent_version_returns_404(auth_client):
    detail_url = reverse("graph-versions-detail", args=[99999])

    response = auth_client.get(detail_url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# ---------------------------------------------------------------------------
# Group E: create-graph action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_graph_returns_201_with_response_dict_structure(
    auth_client, graph, make_graph_version
):
    version = make_graph_version(name="snap-for-create")
    version_id = version["id"]

    url = reverse("graph-versions-create-graph", args=[version_id])
    response = auth_client.post(url, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["created"] is True
    assert "graph_id" in response.data
    assert isinstance(response.data["warnings"], list)


@pytest.mark.django_db
def test_create_graph_creates_new_graph_with_version_name(
    auth_client, graph, make_graph_version
):
    version_name = "unique-version-xyz"
    version = make_graph_version(name=version_name)
    version_id = version["id"]

    url = reverse("graph-versions-create-graph", args=[version_id])
    response = auth_client.post(url, format="json")

    expected_name = f"{graph.name} from {version_name}"

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(id=response.data["graph_id"])
    assert new_graph.name == expected_name


@pytest.mark.django_db
def test_create_graph_unique_name_collision_appends_suffix(
    auth_client, graph, make_graph_version
):
    # Version name collides with the source graph name
    version = make_graph_version(name=graph.name)
    version_id = version["id"]

    url = reverse("graph-versions-create-graph", args=[version_id])
    response = auth_client.post(url, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(id=response.data["graph_id"])
    # Name must be unique — not equal to the source graph's name
    assert new_graph.name != graph.name
    assert graph.name in new_graph.name


@pytest.mark.django_db
def test_create_graph_nonexistent_version_returns_404(auth_client):
    url = reverse("graph-versions-create-graph", args=[99999])

    response = auth_client.post(url, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_create_graph_response_contains_warnings_list(
    auth_client, graph, make_graph_version
):
    version = make_graph_version(name="warnings-check")
    version_id = version["id"]

    url = reverse("graph-versions-create-graph", args=[version_id])
    response = auth_client.post(url, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert "warnings" in response.data
    assert isinstance(response.data["warnings"], list)


# ---------------------------------------------------------------------------
# Group F: Optimistic locking — restore_version
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_version_success_increments_save_version(
    auth_client, graph, make_graph_version
):
    """Correct save_version → 200, restore happens, save_version bumped."""
    version = make_graph_version(name="for-lock-restore")
    version_id = version["id"]

    graph.refresh_from_db()
    version_before = graph.save_version

    restore_url = reverse("graph-versions-restore", args=[version_id])
    response = auth_client.post(
        restore_url,
        {"save_version": version_before},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["restored"] is True
    graph.refresh_from_db()
    assert graph.save_version == version_before + 1


@pytest.mark.django_db
def test_restore_version_stale_save_version_returns_409(
    auth_client, graph, make_graph_version
):
    """Stale save_version → 409, no restore side effects, no auto-backup."""
    version = make_graph_version(name="for-stale-restore")
    version_id = version["id"]

    Graph.objects.filter(pk=graph.pk).update(save_version=50)
    versions_before = GraphVersion.objects.filter(graph=graph).count()

    restore_url = reverse("graph-versions-restore", args=[version_id])
    response = auth_client.post(
        restore_url + "?backup=true",
        {"save_version": 1},  # stale
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    # No new backup row should have been created
    assert GraphVersion.objects.filter(graph=graph).count() == versions_before
