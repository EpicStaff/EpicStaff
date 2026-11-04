"""Attaching files to a flow hands them to every granted node of the flow, so it needs their permissions."""

from unittest.mock import patch

import pytest
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, GraphStorageFile, PythonCode
from tables.models.graph_models import PythonNode, TaskNode
from tables.services.storage_service.manager import StorageManager
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from tests.storage_tests.storage_writes import store_object

pytestmark = pytest.mark.django_db

ADD = "/api/storage/add-to-graph/"
REMOVE = "/api/storage/remove-from-graph/"


@pytest.fixture(autouse=True)
def store():
    backend = InMemoryStorageBackend(organization_prefix="")
    with patch(
        "tables.views.storage_views.get_storage_manager", return_value=StorageManager(backend)
    ):
        yield backend


@pytest.fixture
def flow(acme, store):
    store_object(store, acme.id, "report.txt", b"x")
    return Graph.objects.create(name="attach-flow", org=acme)


@pytest.fixture
def editor(client_as, custom_role_user, acme):
    def _make(email, files):
        permissions = {
            ResourceType.FLOWS: Permission.READ | Permission.UPDATE,
            ResourceType.FILES: files,
        }
        client = client_as(custom_role_user(acme, email, permissions))
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


def _granted_node(flow, **flags):
    return PythonNode.objects.create(
        graph=flow,
        python_code=PythonCode.objects.create(code="x", entrypoint="main"),
        **flags,
    )


def _attach(client, flow):
    return client.post(ADD, {"paths": ["report.txt"], "graph_ids": [flow.id]}, format="json")


def test_attaching_to_a_flow_with_a_granted_node_needs_that_grants_permissions(flow, editor):
    _granted_node(flow, storage_grant_read=True, storage_grant_write=True, storage_grant_delete=False)
    reader = editor("reader@example.com", Permission.READ)

    refused = _attach(reader, flow)

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"] == (
        "This code runs with Files: Create, Files: Update, which you don't have. Contact an admin to change it."
    )
    assert refused.data["missing_grants"] == ["write"]
    assert not GraphStorageFile.objects.filter(graph=flow).exists()


def test_a_user_holding_every_granted_permission_may_attach(flow, editor):
    _granted_node(flow, storage_grant_read=True, storage_grant_write=True, storage_grant_delete=False)
    holder = editor(
        "holder@example.com", Permission.READ | Permission.CREATE | Permission.UPDATE
    )

    response = _attach(holder, flow)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert GraphStorageFile.objects.filter(graph=flow).count() == 1


def test_the_grants_of_every_node_type_in_the_flow_count(flow, editor):
    TaskNode.objects.create(
        graph=flow, storage_grant_read=False, storage_grant_write=False, storage_grant_delete=True
    )
    reader = editor("reader2@example.com", Permission.READ)

    response = _attach(reader, flow)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["missing_grants"] == ["delete"]


@pytest.mark.parametrize(
    "flags",
    [{}, {"storage_grant_read": False, "storage_grant_write": False, "storage_grant_delete": False}],
    ids=["not-configured", "granted-nothing"],
)
def test_a_flow_without_granted_nodes_can_be_attached_to_by_anyone_who_may_edit_flows(
    flow, editor, flags
):
    _granted_node(flow, **flags)
    nobody = editor("nobody@example.com", Permission.READ)

    assert _attach(nobody, flow).status_code == status.HTTP_201_CREATED


def test_detaching_needs_no_grant_permission(flow, editor):
    node_flags = {"storage_grant_read": True, "storage_grant_write": True, "storage_grant_delete": True}
    _granted_node(flow, **node_flags)
    admin_like = editor(
        "full@example.com",
        Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE,
    )
    assert _attach(admin_like, flow).status_code == status.HTTP_201_CREATED
    nobody = editor("nobody2@example.com", Permission.READ)

    response = nobody.delete(REMOVE, {"paths": ["report.txt"], "graph_ids": [flow.id]}, format="json")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not GraphStorageFile.objects.filter(graph=flow).exists()


def test_another_orgs_flow_is_still_rejected_as_not_found(beta, editor, flow):
    other_flow = Graph.objects.create(name="beta-flow", org=beta)
    _granted_node(other_flow, storage_grant_read=True, storage_grant_write=True, storage_grant_delete=True)
    nobody = editor("nobody3@example.com", Permission.READ)

    response = _attach(nobody, other_flow)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "not found" in str(response.data).lower()


def test_a_file_restored_from_the_storage_recycle_bin_is_not_linked_to_flows_again(
    acme, store, flow, editor
):
    from tables.models import StorageFile

    full = editor(
        "binner@example.com",
        Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE,
    )
    assert _attach(full, flow).status_code == status.HTTP_201_CREATED
    assert full.delete("/api/storage/delete/", {"paths": ["report.txt"]}, format="json").status_code == 204
    assert not GraphStorageFile.objects.filter(graph=flow).exists()
    binned = StorageFile.deleted_objects.get(org=acme, path="report.txt")

    restored = full.post("/api/storage/recycle-bin/restore/", {"ids": [binned.pk]}, format="json")

    assert restored.status_code == status.HTTP_200_OK, restored.content
    assert restored.json()["restored"][0]["links_restored"] is False
    assert StorageFile.objects.filter(org=acme, path="report.txt").exists()
    assert not GraphStorageFile.objects.filter(graph=flow).exists()
