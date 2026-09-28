from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
    assert created.data["updated_by_graph"] is None
    assert created.data["updated_by_graph_name"] is None

    listed = admin_client.get(ENTRIES_URL, {"table": table_a.id})
    assert [row["key"] for row in _results(listed)] == ["k1"]

    updated = admin_client.patch(f"{ENTRIES_URL}{created.data['id']}/", {"value": [1, 2]}, format="json")
    assert updated.status_code == 200
    assert updated.data["value"] == [1, 2]

    assert admin_client.delete(f"{ENTRIES_URL}{created.data['id']}/").status_code == 204


@pytest.mark.django_db
def test_entry_list_sends_value_preview_instead_of_value(admin_client, table_a):
    long_value = {"text": "x" * 500}
    PersistenceTableEntry.objects.create(table=table_a, key="long", value=long_value)
    PersistenceTableEntry.objects.create(table=table_a, key="null", value=None)
    PersistenceTableEntry.objects.create(table=table_a, key="short", value={"a": 1})

    rows = {row["key"]: row for row in _results(admin_client.get(ENTRIES_URL, {"table": table_a.id}))}

    assert all("value" not in row for row in rows.values())
    assert rows["long"]["value_preview"] == ('{"text": "' + "x" * 500)[:200]
    assert rows["long"]["value_truncated"] is True
    assert (rows["short"]["value_preview"], rows["short"]["value_truncated"]) == ('{"a": 1}', False)
    assert (rows["null"]["value_preview"], rows["null"]["value_truncated"]) == ("null", False)


@pytest.mark.django_db
def test_entry_list_previews_only_the_page(admin_client, table_a):
    for key in ("a", "b", "c"):
        PersistenceTableEntry.objects.create(table=table_a, key=key, value={"key": key})

    with CaptureQueriesContext(connection) as captured:
        response = admin_client.get(ENTRIES_URL, {"table": table_a.id, "ordering": "-key", "limit": 2})

    assert _keys(response) == ["c", "b"]
    preview_queries = [query["sql"] for query in captured if 'AS "value_preview"' in query["sql"]]
    assert len(preview_queries) == 1
    assert '"tables_persistencetableentry"."id" IN (' in preview_queries[0]


@pytest.mark.django_db
def test_entry_detail_returns_full_value(admin_client, table_a):
    long_value = {"text": "x" * 500}
    entry = PersistenceTableEntry.objects.create(table=table_a, key="long", value=long_value)

    response = admin_client.get(f"{ENTRIES_URL}{entry.id}/")

    assert response.status_code == 200
    assert response.data["value"] == long_value
    assert "value_preview" not in response.data


@pytest.mark.django_db
def test_entry_write_responses_carry_full_value(admin_client, table_a):
    long_value = {"text": "x" * 500}

    created = admin_client.post(
        ENTRIES_URL, {"table": table_a.id, "key": "k", "value": long_value}, format="json"
    )
    renamed = admin_client.patch(f"{ENTRIES_URL}{created.data['id']}/", {"key": "k2"}, format="json")
    replaced = admin_client.put(
        f"{ENTRIES_URL}{created.data['id']}/",
        {"table": table_a.id, "key": "k2", "value": [1, 2]},
        format="json",
    )

    assert (created.status_code, created.data["value"]) == (201, long_value)
    assert (renamed.status_code, renamed.data["value"]) == (200, long_value)
    assert (replaced.status_code, replaced.data["value"]) == (200, [1, 2])


@pytest.mark.django_db
def test_duplicate_entry_key_is_400(admin_client, table_a):
    PersistenceTableEntry.objects.create(table=table_a, key="k1", value=1)
    response = admin_client.post(ENTRIES_URL, {"table": table_a.id, "key": "k1", "value": 2}, format="json")
    assert response.status_code == 400
    # The global exception handler flattens field errors into `message`.
    assert response.data["message"] == "key: An entry with this key already exists in this table."
    assert PersistenceTableEntry.objects.get(table=table_a, key="k1").value == 1


@pytest.mark.django_db
def test_hand_edit_clears_run_attribution(admin_client, org_a, table_a):
    graph = Graph.objects.create(name="Writer flow", org=org_a)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    entry = PersistenceTableEntry.objects.create(table=table_a, key="k", value=1, updated_by_session=session)

    listed = _results(admin_client.get(ENTRIES_URL, {"table": table_a.id}))
    assert listed[0]["updated_by_session"] == session.id
    assert listed[0]["updated_by_graph"] == graph.id
    assert listed[0]["updated_by_graph_name"] == "Writer flow"
    detail = admin_client.get(f"{ENTRIES_URL}{entry.id}/")
    assert (detail.data["updated_by_graph"], detail.data["updated_by_graph_name"]) == (
        graph.id,
        "Writer flow",
    )

    updated = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"value": 2}, format="json")
    assert updated.status_code == 200
    assert updated.data["updated_by_session"] is None
    assert updated.data["updated_by_graph"] is None
    assert updated.data["updated_by_graph_name"] is None


@pytest.mark.django_db
def test_entry_list_query_count_does_not_grow_with_writer_sessions(admin_client, org_a, table_a):
    def list_query_count() -> int:
        with CaptureQueriesContext(connection) as captured:
            response = admin_client.get(ENTRIES_URL, {"table": table_a.id})
        assert response.status_code == 200
        return len(captured)

    def add_entry_written_by_new_flow(index: int) -> None:
        graph = Graph.objects.create(name=f"Flow {index}", org=org_a)
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
        PersistenceTableEntry.objects.create(
            table=table_a, key=f"k{index}", value=index, updated_by_session=session
        )

    add_entry_written_by_new_flow(0)
    list_query_count()
    few = list_query_count()
    for index in range(1, 4):
        add_entry_written_by_new_flow(index)
    many = list_query_count()

    assert many == few
    names = [row["updated_by_graph_name"] for row in _results(admin_client.get(ENTRIES_URL, {"table": table_a.id}))]
    assert names == ["Flow 0", "Flow 1", "Flow 2", "Flow 3"]


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "put"])
def test_entry_rename_keeps_value_and_clears_run_attribution(admin_client, org_a, table_a, method):
    graph = Graph.objects.create(name="Writer flow", org=org_a)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    entry = PersistenceTableEntry.objects.create(
        table=table_a, key="old", value={"a": 1}, updated_by_session=session
    )
    body = {"key": "new"} if method == "patch" else {"table": table_a.id, "key": "new", "value": {"a": 1}}

    response = getattr(admin_client, method)(f"{ENTRIES_URL}{entry.id}/", body, format="json")

    assert response.status_code == 200, response.content
    assert response.data["key"] == "new"
    assert response.data["updated_by_session"] is None
    assert response.data["updated_by_graph_name"] is None
    entry.refresh_from_db()
    assert (entry.key, entry.value, entry.updated_by_session_id) == ("new", {"a": 1}, None)


@pytest.mark.django_db
def test_entry_rename_onto_existing_key_is_400(admin_client, table_a):
    PersistenceTableEntry.objects.create(table=table_a, key="taken", value=1)
    entry = PersistenceTableEntry.objects.create(table=table_a, key="mine", value=2)

    response = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"key": "taken"}, format="json")

    assert response.status_code == 400
    assert response.data["message"] == "key: An entry with this key already exists in this table."
    entry.refresh_from_db()
    assert entry.key == "mine"


@pytest.mark.django_db
def test_entry_rename_to_key_used_in_another_table_is_allowed(admin_client, org_a, table_a):
    other_table = PersistenceTable.objects.create(org=org_a, name="Other")
    PersistenceTableEntry.objects.create(table=other_table, key="shared", value=1)
    entry = PersistenceTableEntry.objects.create(table=table_a, key="mine", value=2)

    response = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"key": "shared"}, format="json")

    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_entry_rename_cross_org_is_404(admin_client, table_b):
    entry = PersistenceTableEntry.objects.create(table=table_b, key="k", value=1)

    response = admin_client.patch(f"{ENTRIES_URL}{entry.id}/", {"key": "renamed"}, format="json")

    assert response.status_code == 404
    entry.refresh_from_db()
    assert entry.key == "k"


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


@pytest.fixture
def ordering_entries(org_a, table_a):
    """Five entries with ties on `updated_at` and on session, two without a session."""
    graph = Graph.objects.create(name="Writer flow", org=org_a)
    first_session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    second_session = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    base = timezone.now()
    rows = [
        ("b", second_session, 1),
        ("a", first_session, 3),
        ("c", None, 2),
        ("d", first_session, 1),
        ("e", None, 2),
    ]
    for key, session, hours in rows:
        entry = PersistenceTableEntry.objects.create(
            table=table_a, key=key, value=key, updated_by_session=session
        )
        # update() skips auto_now, so the timestamps stick.
        PersistenceTableEntry.objects.filter(id=entry.id).update(
            updated_at=base + timedelta(hours=hours)
        )


def _keys(response) -> list[str]:
    assert response.status_code == 200, response.content
    return [row["key"] for row in _results(response)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("ordering", "expected"),
    [
        (None, ["a", "b", "c", "d", "e"]),
        ("key", ["a", "b", "c", "d", "e"]),
        ("-key", ["e", "d", "c", "b", "a"]),
        ("updated_at", ["b", "d", "c", "e", "a"]),
        ("-updated_at", ["a", "c", "e", "b", "d"]),
        ("session", ["a", "d", "b", "c", "e"]),
        ("-session", ["b", "a", "d", "c", "e"]),
        ("session,-updated_at", ["a", "d", "b", "c", "e"]),
        ("session,updated_at", ["d", "a", "b", "c", "e"]),
    ],
)
def test_entry_ordering(admin_client, table_a, ordering_entries, ordering, expected):
    params = {"table": table_a.id}
    if ordering is not None:
        params["ordering"] = ordering

    assert _keys(admin_client.get(ENTRIES_URL, params)) == expected


@pytest.mark.django_db
@pytest.mark.parametrize("ordering", ["bogus", "value", "-table", "--key", "created_at", ""])
def test_entry_unknown_ordering_falls_back_to_key(admin_client, table_a, ordering_entries, ordering):
    response = admin_client.get(ENTRIES_URL, {"table": table_a.id, "ordering": ordering})

    assert _keys(response) == ["a", "b", "c", "d", "e"]


@pytest.mark.django_db
def test_entry_ordering_ties_on_same_key_break_by_id(admin_client, org_a, table_a):
    other_table = PersistenceTable.objects.create(org=org_a, name="Other")
    first = PersistenceTableEntry.objects.create(table=table_a, key="shared", value=1)
    second = PersistenceTableEntry.objects.create(table=other_table, key="shared", value=2)

    for ordering in ("-key", "session", "-session"):
        response = admin_client.get(ENTRIES_URL, {"ordering": ordering})
        assert [row["id"] for row in _results(response)] == [first.id, second.id], ordering


@pytest.mark.django_db
@pytest.mark.parametrize("ordering", ["session", "-session", "updated_at", "-updated_at"])
def test_entry_ordering_pages_are_stable(admin_client, table_a, ordering_entries, ordering):
    full = _keys(admin_client.get(ENTRIES_URL, {"table": table_a.id, "ordering": ordering}))

    paged = []
    for offset in range(0, 5, 2):
        paged += _keys(
            admin_client.get(
                ENTRIES_URL, {"table": table_a.id, "ordering": ordering, "limit": 2, "offset": offset}
            )
        )

    assert paged == full
    assert sorted(paged) == ["a", "b", "c", "d", "e"]


@pytest.mark.django_db
def test_entry_ordering_with_search_and_pagination(admin_client, table_a):
    for index in range(4):
        PersistenceTableEntry.objects.create(table=table_a, key=f"order_{index}", value=index)
    PersistenceTableEntry.objects.create(table=table_a, key="profile_9", value=9)

    response = admin_client.get(
        ENTRIES_URL,
        {"table": table_a.id, "search": "order", "ordering": "-key", "limit": 2, "offset": 1},
    )

    assert response.data["count"] == 4
    assert _keys(response) == ["order_2", "order_1"]


@pytest.mark.django_db
def test_entry_ordering_keeps_org_scope_and_annotations(admin_client, table_a, table_b, ordering_entries):
    PersistenceTableEntry.objects.create(table=table_b, key="0_foreign", value=1)

    rows = _results(admin_client.get(ENTRIES_URL, {"ordering": "session"}))

    assert [row["key"] for row in rows] == ["a", "d", "b", "c", "e"]
    assert [row["updated_by_graph_name"] for row in rows] == ["Writer flow"] * 3 + [None, None]


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
