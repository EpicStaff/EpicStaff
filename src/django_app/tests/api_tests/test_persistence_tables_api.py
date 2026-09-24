import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tables.models import Graph, PersistenceNode, PersistenceTable, PersistenceTableEntry, Session
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

TABLES_URL = "/api/persistence-tables/"
ENTRIES_URL = "/api/persistence-table-entries/"


def _results(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _client_for(django_user_model, org, role_name, email) -> APIClient:
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="pw")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def admin_client(django_user_model, org_a):
    return _client_for(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "admin@a.test")


@pytest.fixture
def member_client(django_user_model, org_a):
    return _client_for(django_user_model, org_a, BuiltInRole.MEMBER, "member@a.test")


@pytest.fixture
def table_a(org_a):
    return PersistenceTable.objects.create(org=org_a, name="Customers")


@pytest.fixture
def table_b(org_b):
    return PersistenceTable.objects.create(org=org_b, name="Theirs")


# --- tables ---------------------------------------------------------------

@pytest.mark.django_db
def test_create_table_lands_in_active_org(admin_client, org_a):
    response = admin_client.post(TABLES_URL, {"name": " Orders ", "description": "d"}, format="json")
    assert response.status_code == 201, response.content
    table = PersistenceTable.objects.get(id=response.data["id"])
    assert table.org_id == org_a.id
    assert table.name == "Orders"
    assert table.created_by is not None
    assert response.data["entry_count"] == 0


@pytest.mark.django_db
def test_duplicate_name_case_insensitive_is_400(admin_client, table_a):
    response = admin_client.post(TABLES_URL, {"name": "customers"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_whitespace_only_name_is_400(admin_client):
    response = admin_client.post(TABLES_URL, {"name": "   "}, format="json")
    assert response.status_code == 400
    assert not PersistenceTable.objects.exists()


@pytest.mark.django_db
def test_rename_to_own_name_in_other_case_is_allowed(admin_client, table_a):
    response = admin_client.patch(f"{TABLES_URL}{table_a.id}/", {"name": "CUSTOMERS"}, format="json")
    assert response.status_code == 200, response.content
    table_a.refresh_from_db()
    assert table_a.name == "CUSTOMERS"


@pytest.mark.django_db
def test_list_only_active_org_with_entry_count(admin_client, table_a, table_b):
    PersistenceTableEntry.objects.create(table=table_a, key="k", value=1)
    response = admin_client.get(TABLES_URL)
    rows = _results(response)
    assert [row["name"] for row in rows] == ["Customers"]
    assert rows[0]["entry_count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_table_detail_cross_org_is_404(admin_client, table_b, method):
    response = getattr(admin_client, method)(f"{TABLES_URL}{table_b.id}/", {"name": "x"}, format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_member_can_read_but_not_create_or_delete(member_client, table_a):
    assert member_client.get(TABLES_URL).status_code == 200
    assert member_client.post(TABLES_URL, {"name": "New"}, format="json").status_code == 403
    assert member_client.delete(f"{TABLES_URL}{table_a.id}/").status_code == 403


@pytest.mark.django_db
def test_delete_table_in_use_is_409_with_flow_names(admin_client, org_a, table_a):
    graph = Graph.objects.create(name="Billing flow", org=org_a)
    PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table_a)
    response = admin_client.delete(f"{TABLES_URL}{table_a.id}/")
    assert response.status_code == 409
    assert "Billing flow" in response.data["message"]
    assert PersistenceTable.objects.filter(id=table_a.id).exists()


@pytest.mark.django_db
def test_delete_table_referenced_only_by_soft_deleted_node(admin_client, org_a, table_a):
    graph = Graph.objects.create(name="Old flow", org=org_a)
    node = PersistenceNode.objects.create(graph=graph, node_name="p", persistence_table=table_a)
    node.is_soft_deleted = True
    node.soft_deleted_at = timezone.now()
    node.save()

    response = admin_client.delete(f"{TABLES_URL}{table_a.id}/")

    assert response.status_code == 204
    assert PersistenceNode.all_objects.get(id=node.id).persistence_table_id is None


# --- entries --------------------------------------------------------------

@pytest.mark.django_db
def test_entry_crud(admin_client, table_a):
    created = admin_client.post(ENTRIES_URL, {"table": table_a.id, "key": "k1", "value": {"a": 1}}, format="json")
    assert created.status_code == 201, created.content

    listed = admin_client.get(ENTRIES_URL, {"table": table_a.id})
    assert [row["key"] for row in _results(listed)] == ["k1"]

    updated = admin_client.patch(f"{ENTRIES_URL}{created.data['id']}/", {"value": [1, 2]}, format="json")
    assert updated.status_code == 200
    assert updated.data["value"] == [1, 2]

    assert admin_client.delete(f"{ENTRIES_URL}{created.data['id']}/").status_code == 204


@pytest.mark.django_db
def test_duplicate_entry_key_is_400(admin_client, table_a):
    PersistenceTableEntry.objects.create(table=table_a, key="k1", value=1)
    response = admin_client.post(ENTRIES_URL, {"table": table_a.id, "key": "k1", "value": 2}, format="json")
    assert response.status_code == 400
    assert PersistenceTableEntry.objects.get(table=table_a, key="k1").value == 1


@pytest.mark.django_db
def test_hand_edit_clears_run_attribution(admin_client, org_a, table_a):
    graph = Graph.objects.create(name="Writer flow", org=org_a)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    entry = PersistenceTableEntry.objects.create(table=table_a, key="k", value=1, updated_by_session=session)

    listed = _results(admin_client.get(ENTRIES_URL, {"table": table_a.id}))
    assert listed[0]["updated_by_session"] == session.id
    assert listed[0]["updated_by_graph"] == graph.id

    updated = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"value": 2}, format="json")
    assert updated.status_code == 200
    assert updated.data["updated_by_session"] is None
    assert updated.data["updated_by_graph"] is None


@pytest.mark.django_db
def test_entry_filter_by_foreign_table_matches_missing_table(admin_client, table_b):
    PersistenceTableEntry.objects.create(table=table_b, key="k", value=1)
    foreign = admin_client.get(ENTRIES_URL, {"table": table_b.id})
    missing = admin_client.get(ENTRIES_URL, {"table": table_b.id + 100000})
    assert foreign.status_code == missing.status_code == 200
    assert _results(foreign) == _results(missing) == []


@pytest.mark.django_db
def test_entry_search_and_pagination(admin_client, table_a):
    for index in range(3):
        PersistenceTableEntry.objects.create(table=table_a, key=f"order_{index}", value=index)
    PersistenceTableEntry.objects.create(table=table_a, key="profile_1", value=1)

    response = admin_client.get(ENTRIES_URL, {"table": table_a.id, "search": "order", "limit": 2, "offset": 0})
    assert response.data["count"] == 3
    assert [row["key"] for row in response.data["results"]] == ["order_0", "order_1"]


@pytest.mark.django_db
def test_entry_list_limit_is_capped(admin_client, table_a):
    PersistenceTableEntry.objects.bulk_create(
        [PersistenceTableEntry(table=table_a, key=f"k{index}", value=index) for index in range(101)]
    )

    response = admin_client.get(ENTRIES_URL, {"table": table_a.id, "limit": 1000})

    assert response.data["count"] == 101
    assert len(response.data["results"]) == 100


@pytest.mark.django_db
def test_entry_for_foreign_table_is_rejected(admin_client, table_b):
    response = admin_client.post(ENTRIES_URL, {"table": table_b.id, "key": "k", "value": 1}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_entry_cross_org_detail_is_404(admin_client, table_b, method):
    entry = PersistenceTableEntry.objects.create(table=table_b, key="k", value=1)
    response = getattr(admin_client, method)(f"{ENTRIES_URL}{entry.id}/", {"value": 2}, format="json")
    assert response.status_code == 404
    entry.refresh_from_db()
    assert entry.value == 1


@pytest.mark.django_db
def test_entry_cannot_be_moved_to_another_table(admin_client, org_a, table_a):
    other_table = PersistenceTable.objects.create(org=org_a, name="Other")
    entry = PersistenceTableEntry.objects.create(table=table_a, key="k", value=1)

    response = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"table": other_table.id}, format="json")

    assert response.status_code == 400
    entry.refresh_from_db()
    assert entry.table_id == table_a.id


@pytest.mark.django_db
def test_entry_put_with_its_own_table_is_allowed(admin_client, table_a):
    entry = PersistenceTableEntry.objects.create(table=table_a, key="k", value=1)

    response = admin_client.put(
        f"{ENTRIES_URL}{entry.id}/", {"table": table_a.id, "key": "k", "value": 2}, format="json"
    )

    assert response.status_code == 200, response.content
    entry.refresh_from_db()
    assert entry.value == 2


@pytest.mark.django_db
def test_oversized_entry_is_400(admin_client, table_a):
    response = admin_client.post(ENTRIES_URL, {"table": table_a.id, "key": "k", "value": "x" * 262144}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_member_cannot_edit_entries(member_client, table_a):
    response = member_client.post(ENTRIES_URL, {"table": table_a.id, "key": "k", "value": 1}, format="json")
    assert response.status_code == 403


# --- lookup ---------------------------------------------------------------

@pytest.mark.django_db
def test_lookup_entries(member_client, table_a):
    PersistenceTableEntry.objects.create(table=table_a, key="k1", value="v")
    response = member_client.post(f"{TABLES_URL}{table_a.id}/entries/lookup/", {"keys": ["k1", "nope"]}, format="json")
    assert response.status_code == 200
    assert response.data["k1"]["exists"] is True
    assert response.data["k1"]["value_preview"] == '"v"'
    assert response.data["nope"] == {"exists": False, "value_preview": None, "updated_at": None}


@pytest.mark.django_db
def test_lookup_cross_org_is_404(admin_client, table_b):
    response = admin_client.post(f"{TABLES_URL}{table_b.id}/entries/lookup/", {"keys": ["k"]}, format="json")
    assert response.status_code == 404
