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
        "entries": [{"key": "profile_{variables.user.id}", "value": "variables.customer"}],
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
    assert node.entries == [{"key": "profile_{variables.user.id}", "value": "variables.customer"}]


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
        entries=[{"key": "k", "value": "variables.a"}],
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
    assert node.entries == [{"key": "k", "value": "variables.a"}]


@pytest.mark.django_db
def test_mode_change_validates_stored_entries(auth_client, graph, table):
    node = PersistenceNode.objects.create(
        graph=graph, node_name="p", persistence_table=table, mode="read",
        entries=[{"key": "k", "value": "variables.a"}],
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
        ("read", [{"key": "k"}]),  # missing value
        ("read", [{"key": "k", "value": "user.name"}]),  # not a state path
        ("read", [{"key": "k", "value": "variables"}]),  # bare root
        ("read", [{"key": "k", "value": "variables.a", "alias": "a"}]),  # alias is gone
        ("read", [{"key": "k", "value": "variables.a", "default": 0}]),  # default is gone
        ("write", [{"key": "k"}]),  # missing value
        ("write", [{"key": "k", "value": "value"}]),  # not a state path
        ("write", [{"key": "k", "value": "variables"}]),  # bare root
        ("write", [{"key": "k", "value": "variables."}]),  # empty segment
        ("write", [{"key": "k", "value": "variables[0]"}]),  # state root is not a list
        ("write", [{"key": "k", "value": "variables[0].a"}]),  # state root is not a list
        ("delete", [{"key": ""}]),  # empty key
        ("delete", [{"key": "k", "value": "variables.x"}]),  # unknown field for mode
        ("read", {"key": "k", "value": "variables.a"}),  # not a list
    ],
)
def test_invalid_entries_are_rejected(auth_client, graph, table, mode, entries):
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


STATE_PATH_MESSAGE = "'value' must be a state path like 'variables.user.name'."


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write"])
@pytest.mark.parametrize(
    "value, message",
    [
        ("variables.user name", STATE_PATH_MESSAGE),
        ("variables.a..b", STATE_PATH_MESSAGE),
        ("variables.a.", STATE_PATH_MESSAGE),
        ("variables.tags[x]", STATE_PATH_MESSAGE),
        ("variables.tags[0]extra", STATE_PATH_MESSAGE),
        ("variables.naïve", STATE_PATH_MESSAGE),
        ("variables._properties", "'value' names '_properties'; use a variable name without the leading '_'."),
        ("variables.user.__dict__", "'value' names '__dict__'; use a variable name without the leading '_'."),
        ("variables.cart.items", "'value' names 'items', a built-in method; use a different variable name."),
        ("variables.deep_dump[0]", "'value' names 'deep_dump', a built-in method; use a different variable name."),
    ],
)
def test_value_path_rules_apply_to_read_and_write(auth_client, graph, table, mode, value, message):
    entries = [{"key": "k", "value": value}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert f"Entry 0: {message}" in str(response.data)


@pytest.mark.django_db
def test_write_source_is_checked_before_its_default(auth_client, graph, table):
    entries = [{"key": "k", "value": "variables.cart.items|0"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "'value' names 'items', a built-in method" in str(response.data)


@pytest.mark.django_db
def test_write_value_must_name_a_state_path(auth_client, graph, table):
    entries = [{"key": "k", "value": "user.name"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Entry 0: 'value' must be a state path like 'variables.user.name'." in str(
        response.data
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value",
    [
        "variables.a",
        "variables.a.b",
        "variables.a[0]",
        "variables.x|0",
        "  variables.a  ",
        "  variables.x|0  ",
    ],
)
def test_write_state_path_values_are_saved_stripped(auth_client, graph, table, value):
    entries = [{"key": "k", "value": value}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries == [{"key": "k", "value": value.strip()}]


@pytest.mark.django_db
def test_read_value_with_default_is_rejected(auth_client, graph, table):
    entries = [{"key": "k", "value": "variables.a|0"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Entry 0: 'value' is where the stored value goes" in str(response.data)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "entries",
    [
        # Two keys into one variable: crew applies them in order, the later one wins.
        [{"key": "k1", "value": "variables.a"}, {"key": "k2", "value": "variables.a"}],
        # One key into two variables.
        [{"key": "k", "value": "variables.a"}, {"key": "k", "value": "variables.b"}],
    ],
)
def test_read_entries_may_share_a_key_or_a_variable(auth_client, graph, table, entries):
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries == entries


@pytest.mark.django_db
def test_write_entries_must_use_different_keys(auth_client, graph, table):
    entries = [
        {"key": "k_{variables.id}", "value": "variables.a"},
        {"key": "other", "value": "variables.b"},
        {"key": "k_{variables.id}", "value": "variables.c"},
    ]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "Entry 2: key 'k_{variables.id}' is already written by entry 0; use a different key."
        in str(response.data)
    )
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_write_keys_are_compared_exactly(auth_client, graph, table):
    # Crew renders templates at run time and rejects keys that collide there.
    entries = [{"key": "k", "value": "variables.a"}, {"key": "k ", "value": "variables.b"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "second_value",
    ["variables.a", " variables.a ", "variables.a|0", "variables.a|1"],
)
def test_one_source_may_feed_several_write_keys(auth_client, graph, table, second_value):
    entries = [{"key": "k1", "value": "variables.a"}, {"key": "k2", "value": second_value}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries == [
        {"key": "k1", "value": "variables.a"},
        {"key": "k2", "value": second_value.strip()},
    ]


@pytest.mark.django_db
def test_same_key_and_source_twice_is_rejected(auth_client, graph, table):
    entries = [{"key": "k2", "value": "variables.a"}, {"key": "k2", "value": "variables.a"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Entry 1: key 'k2' is already written by entry 0; use a different key." in str(
        response.data
    )
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_write_source_nested_in_another_is_accepted(auth_client, graph, table):
    entries = [{"key": "k1", "value": "variables.user"}, {"key": "k2", "value": "variables.user.id"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_read_values_are_saved_stripped(auth_client, graph, table):
    entries = [{"key": "k1", "value": "  variables.a  "}, {"key": "k2", "value": "variables.b[0]"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries == [
        {"key": "k1", "value": "variables.a"},
        {"key": "k2", "value": "variables.b[0]"},
    ]


@pytest.mark.django_db
def test_delete_node_through_bulk_save(auth_client, graph, table):
    node = PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table)
    payload = {"save_version": graph.save_version, "deleted": {"persistence_node_ids": [node.id]}}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PersistenceNode.objects.filter(id=node.id).exists()
