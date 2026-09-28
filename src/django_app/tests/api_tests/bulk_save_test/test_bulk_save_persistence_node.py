import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import PersistenceNode, PersistenceTable
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission
from tests.fixtures import *  # noqa: F401,F403

R = int(Permission.READ)
C = int(Permission.CREATE)
U = int(Permission.UPDATE)
D = int(Permission.DELETE)


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
def client_with_persistent_data(db, django_user_model, default_org):
    """Factory: a client whose role has every flows permission and `bits` on persistent_data."""

    def _make(bits: int) -> APIClient:
        role = Role.objects.create(name=f"Persistent data {bits}", org=default_org, is_built_in=False)
        RolePermission.objects.create(role=role, resource_type="flows", permissions=255)
        RolePermission.objects.create(role=role, resource_type="persistent_data", permissions=bits)
        user = django_user_model.objects.create_user(email=f"pd-{bits}@example.com", password="pw")
        OrganizationUser.objects.create(user=user, org=default_org, role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
        return client

    return _make


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


def _entries_of(mode: str) -> list[dict]:
    if mode == "delete":
        return [{"key": "k"}]
    return [{"key": "k", "value": "variables.a"}]


DENIED_MESSAGES = {
    "read": "You need Key-Value Tables View permission to configure a read node on the table 'Customers'.",
    "write": (
        "You need Key-Value Tables Create and Edit permission to configure a write node on the "
        "table 'Customers'."
    ),
    "delete": "You need Key-Value Tables Delete permission to configure a delete node on the table 'Customers'.",
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bits, mode, allowed",
    [
        (0, "read", False),
        (R, "read", True),
        (R, "write", False),
        (R, "delete", False),
        (R | C, "write", False),
        (R | U, "write", False),
        (R | C | U, "write", True),
        (R | D, "delete", True),
    ],
)
def test_creating_a_node_needs_its_mode_permissions(
    client_with_persistent_data, graph, table, bits, mode, allowed
):
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=_entries_of(mode))],
    }
    response = client_with_persistent_data(bits).post(_save_url(graph.id), payload, format="json")

    if allowed:
        assert response.status_code == status.HTTP_200_OK, response.content
        assert PersistenceNode.objects.get(graph=graph).mode == mode
    else:
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["code"] == "persistence_mode_denied"
        assert response.data["message"] == DENIED_MESSAGES[mode]
        assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_write_node_without_table_needs_no_persistent_data_permission(
    client_with_persistent_data, graph
):
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [_node_payload(graph, None, mode="write", entries=_entries_of("write"))],
    }
    response = client_with_persistent_data(R).post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).persistence_table_id is None


@pytest.fixture
def admin_write_node(graph, table) -> PersistenceNode:
    return PersistenceNode.objects.create(
        graph=graph, node_name="p", persistence_table=table, mode="write",
        entries=[{"key": "k", "value": "variables.a"}], metadata={"position": {"x": 0, "y": 0}},
    )


@pytest.mark.django_db
def test_changing_mode_without_its_permission_is_denied(client_with_persistent_data, graph, table):
    node = PersistenceNode.objects.create(
        graph=graph, node_name="p", persistence_table=table, mode="read",
        entries=[{"key": "k", "value": "variables.a"}],
    )
    # The payload omits the table: the node's saved table is still the one checked.
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [
            {"id": node.id, "graph": graph.id, "mode": "delete", "entries": [{"key": "x"}]}
        ],
    }
    response = client_with_persistent_data(R).post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "persistence_mode_denied"
    assert response.data["message"] == DENIED_MESSAGES["delete"]
    node.refresh_from_db()
    assert node.mode == "read"
    assert node.entries == [{"key": "k", "value": "variables.a"}]


@pytest.mark.django_db
@pytest.mark.parametrize("sends_configuration", [True, False])
def test_viewer_may_rename_and_move_a_write_node_it_cannot_configure(
    client_with_persistent_data, graph, table, admin_write_node, sends_configuration
):
    node_payload = {
        "id": admin_write_node.id,
        "graph": graph.id,
        "node_name": "renamed",
        "metadata": {"position": {"x": 40, "y": 80}},
    }
    if sends_configuration:
        node_payload |= {
            "persistence_table": table.id,
            "mode": "write",
            "entries": [{"key": "k", "value": "variables.a"}],
        }
    payload = {"save_version": graph.save_version, "persistence_node_list": [node_payload]}

    response = client_with_persistent_data(R).post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    admin_write_node.refresh_from_db()
    assert admin_write_node.node_name == "renamed"
    assert admin_write_node.metadata == {"position": {"x": 40, "y": 80}}
    assert admin_write_node.persistence_table_id == table.id
    assert admin_write_node.mode == "write"


@pytest.mark.django_db
def test_viewer_may_not_edit_entries_of_a_write_node(
    client_with_persistent_data, graph, table, admin_write_node
):
    node_payload = {
        "id": admin_write_node.id,
        "graph": graph.id,
        "persistence_table": table.id,
        "mode": "write",
        "entries": [{"key": "other", "value": "variables.a"}],
    }
    payload = {"save_version": graph.save_version, "persistence_node_list": [node_payload]}

    response = client_with_persistent_data(R).post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["code"] == "persistence_mode_denied"
    admin_write_node.refresh_from_db()
    assert admin_write_node.entries == [{"key": "k", "value": "variables.a"}]


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
        ("variables.tags[01]", STATE_PATH_MESSAGE),
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
        "variables.a[10]",
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
def test_read_entries_may_read_one_key_into_two_variables(auth_client, graph, table):
    entries = [{"key": "k", "value": "variables.a"}, {"key": "k", "value": "variables.b"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries == entries


@pytest.mark.django_db
@pytest.mark.parametrize(
    "entries",
    [
        # Two keys into one variable, compared after stripping.
        [
            {"key": "k1", "value": "variables.my_var"},
            {"key": "other", "value": "variables.b"},
            {"key": "k2", "value": " variables.my_var "},
        ],
        # Two identical rows.
        [
            {"key": "k1", "value": "variables.my_var"},
            {"key": "other", "value": "variables.b"},
            {"key": "k1", "value": "variables.my_var"},
        ],
    ],
)
def test_read_entries_must_use_different_variables(auth_client, graph, table, entries):
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "Entry 2: 'variables.my_var' is already filled by entry 0; use a different variable."
        in str(response.data)
    )
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "first, second, message",
    [
        ("variables.user", "variables.user.name",
         "Entry 1: 'variables.user.name' is inside 'variables.user' (entry 0); use a different variable."),
        ("variables.user", " variables.user[0] ",
         "Entry 1: 'variables.user[0]' is inside 'variables.user' (entry 0); use a different variable."),
        ("variables.user.name", "variables.user",
         "Entry 1: 'variables.user' contains 'variables.user.name' (entry 0); use a different variable."),
        ("variables.user[0]", "variables.user",
         "Entry 1: 'variables.user' contains 'variables.user[0]' (entry 0); use a different variable."),
    ],
)
def test_read_targets_must_not_nest(auth_client, graph, table, first, second, message):
    entries = [{"key": "k1", "value": first}, {"key": "k2", "value": second}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert message in str(response.data)
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_read_targets_sharing_only_a_name_prefix_are_accepted(auth_client, graph, table):
    entries = [{"key": "k1", "value": "variables.user"}, {"key": "k2", "value": "variables.username"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content


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
def test_write_key_with_surrounding_whitespace_is_invalid(auth_client, graph, table):
    entries = [{"key": "k", "value": "variables.a"}, {"key": "k ", "value": "variables.b"}]
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode="write", entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Entry 1: 'key' must use only letters, digits and _" in str(response.data)
    assert not PersistenceNode.objects.filter(graph=graph).exists()


# Keep identical to the template parity table in the frontend persistence-node.helpers.spec.ts.
VALID_KEY_TEMPLATES = [
    "k",
    "_",
    "_private",
    "User_1",
    "profile_{variables.user.id}",
    "{variables.id}",
    "{variables.id}_x",
    "{variables.a}{variables.b}",
    "p_{ variables.user.id }",
    "a" * 512,
]
INVALID_KEY_TEMPLATES = [
    "1abc",
    "9_{variables.id}",
    "user-id",
    "user id",
    "k ",
    " k",
    "user.name",
    "naïve",
    "k\n",
    "a" * 513,
    "profile_{}",
    "profile_{variables.x",
    "{{variables.x}}",
    "profile_{user.id}",
    "profile_{variables._x}",
    "profile_{variables.items}",
]


def _entry_with_key(mode: str, key: str) -> dict:
    return {"key": key} if mode == "delete" else {"key": key, "value": "variables.customer"}


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
@pytest.mark.parametrize("key", VALID_KEY_TEMPLATES)
def test_valid_key_templates_are_saved(auth_client, graph, table, mode, key):
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [
            _node_payload(graph, table, mode=mode, entries=[_entry_with_key(mode, key)])
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PersistenceNode.objects.get(graph=graph).entries[0]["key"] == key


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
@pytest.mark.parametrize("key", INVALID_KEY_TEMPLATES)
def test_invalid_key_templates_are_rejected(auth_client, graph, table, mode, key):
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [
            _node_payload(graph, table, mode=mode, entries=[_entry_with_key(mode, key)])
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Entry 0: 'key' " in str(response.data)
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key, message",
    [
        (
            "user-id",
            "Entry 0: 'key' must use only letters, digits and _ outside {placeholders}, and must "
            "not start with a digit, e.g. 'profile_{variables.user.id}'.",
        ),
        (
            "profile_{user.id}",
            "Entry 0: 'key' placeholder 'user.id' must be a state path like 'variables.user.name'.",
        ),
        (
            "profile_{variables.items}",
            "Entry 0: 'key' placeholder 'variables.items' names 'items', a built-in method; "
            "use a different variable name.",
        ),
        (
            "profile_{}",
            "Entry 0: 'key' has an empty or unbalanced placeholder; use '{variables.<path>}', "
            "e.g. 'profile_{variables.user.id}'.",
        ),
    ],
)
def test_invalid_key_template_messages(auth_client, graph, table, key, message):
    payload = {
        "save_version": graph.save_version,
        "persistence_node_list": [
            _node_payload(graph, table, entries=[{"key": key, "value": "variables.customer"}])
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert message in str(response.data)


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


def _entries_for(mode: str, count: int) -> list[dict]:
    if mode == "delete":
        return [{"key": f"k{index}"} for index in range(count)]
    return [{"key": f"k{index}", "value": f"variables.v{index}"} for index in range(count)]


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
def test_more_than_500_entries_are_rejected(auth_client, graph, table, mode):
    entries = _entries_for(mode, 501)
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "A Key-Value node can have at most 500 keys." in str(response.data)
    assert not PersistenceNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
def test_500_entries_are_accepted(auth_client, graph, table, mode):
    entries = _entries_for(mode, 500)
    payload = {"save_version": graph.save_version,
               "persistence_node_list": [_node_payload(graph, table, mode=mode, entries=entries)]}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert len(PersistenceNode.objects.get(graph=graph).entries) == 500


@pytest.mark.django_db
def test_delete_node_through_bulk_save(auth_client, graph, table):
    node = PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table)
    payload = {"save_version": graph.save_version, "deleted": {"persistence_node_ids": [node.id]}}
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PersistenceNode.objects.filter(id=node.id).exists()
