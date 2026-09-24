import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import PersistenceNode, PersistenceTable
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from tests.fixtures import *  # noqa: F401,F403


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _detail_url(graph_id: int) -> str:
    return reverse("graphs-detail", args=[graph_id])


@pytest.fixture
def table(default_org) -> PersistenceTable:
    return PersistenceTable.objects.create(org=default_org, name="Customers")


@pytest.fixture
def foreign_table(db) -> PersistenceTable:
    other = Organization.objects.create(name="Foreign org")
    return PersistenceTable.objects.create(org=other, name="Theirs")


@pytest.fixture
def flows_only_client(db, django_user_model, default_org) -> APIClient:
    role = Role.objects.create(name="Flows only", org=default_org, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type="flows", permissions=255)
    user = django_user_model.objects.create_user(email="flows@example.com", password="pw")
    OrganizationUser.objects.create(user=user, org=default_org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


def _node_payload(graph, table, **overrides) -> dict:
    return {
        "graph": graph.id,
        "node_name": "persist-1",
        "persistence_table": table.id if table else None,
        "mode": "read",
        "entries": [{"alias": "profile", "key": "profile_{user_id}", "default": None}],
        "input_map": {"user_id": "variables.user.id"},
        "output_variable_path": "variables.customer",
        **overrides,
    }


@pytest.mark.django_db
def test_create_persistence_node(auth_client, graph, table):
    payload = {"save_version": graph.save_version, "persistence_node_list": [_node_payload(graph, table)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    node = PersistenceNode.objects.get(graph=graph, node_name="persist-1")
    assert node.persistence_table_id == table.id
    assert node.mode == "read"
    assert node.entries[0]["key"] == "profile_{user_id}"


@pytest.mark.django_db
def test_graph_detail_includes_persistence_nodes(auth_client, graph, table):
    PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table, mode="write",
                                   entries=[{"key": "k", "value": "v"}])
    response = auth_client.get(_detail_url(graph.id))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["persistence_node_list"][0]["mode"] == "write"


@pytest.mark.django_db
def test_cross_org_table_is_rejected(auth_client, graph, foreign_table):
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, foreign_table)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_table_requires_use_permission(flows_only_client, graph, table):
    payload = {"save_version": graph.save_version, "persistence_node_list": [_node_payload(graph, table)]}
    response = flows_only_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "persistence_table_use_denied"
    assert "'Customers'" in response.data["message"]
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_update_without_table_key_still_requires_use_permission(flows_only_client, graph, table):
    node = PersistenceNode.objects.create(
        graph=graph, node_name="p", persistence_table=table, mode="read",
        entries=[{"alias": "a", "key": "k"}],
    )
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [
            {"id": node.id, "graph": graph.id, "mode": "delete", "entries": [{"key": "x"}]}
        ],
    }
    response = flows_only_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "persistence_table_use_denied"
    assert "'Customers'" in response.data["message"]
    node.refresh_from_db()
    assert node.mode == "read"
    assert node.entries == [{"alias": "a", "key": "k"}]


@pytest.mark.django_db
def test_mode_change_validates_stored_entries(auth_client, graph, table):
    node = PersistenceNode.objects.create(
        graph=graph, node_name="p", persistence_table=table, mode="read",
        entries=[{"alias": "a", "key": "k"}],
    )
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [{"id": node.id, "graph": graph.id, "mode": "delete"}],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    node.refresh_from_db()
    assert node.mode == "read"


@pytest.mark.django_db
def test_node_without_table_is_saved(auth_client, graph):
    payload = {"save_version": graph.save_version, "persistence_node_list": [_node_payload(graph, None)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mode, entries",
    [
        ("read", [{"key": "k"}]),  # missing alias
        ("read", [{"alias": "a", "key": "k1"}, {"alias": "a", "key": "k2"}]),  # duplicate alias
        ("write", [{"key": "k"}]),  # missing value alias
        ("delete", [{"key": ""}]),  # empty key
        ("delete", [{"key": "k", "alias": "x"}]),  # unknown field for mode
        ("read", {"alias": "a", "key": "k"}),  # not a list
    ],
)
def test_invalid_entries_are_rejected(auth_client, graph, table, mode, entries):
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_delete_node_through_bulk_save(auth_client, graph, table):
    node = PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table)
    payload = {"save_version": graph.save_version, "deleted": {"persistence_node_ids": [node.id]}}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PersistenceNode.objects.filter(id=node.id).exists()
