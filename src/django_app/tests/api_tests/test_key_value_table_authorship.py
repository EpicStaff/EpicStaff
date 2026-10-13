"""Key-value tables return the same authorship as LLM configs.

`created_by` and `last_edited_by` are user summaries (never an email), `created_at` and
`last_edited_at` ISO times. Only a user's edit through the API is a last edit of the
table: a rename, a description change, or adding, editing or deleting one of its
entries. Values a flow writes at run time record nothing.
"""

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models import Graph, KeyValueNode, KeyValueTable, KeyValueTableEntry, Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

PREVIOUS_EDIT_AT = timezone.now() - timedelta(days=1)
USER_SUMMARY_KEYS = {"id", "display_name", "avatar_url"}
TABLE_KEYS = {
    "id",
    "name",
    "description",
    "entry_count",
    "created_by",
    "created_at",
    "updated_at",
    "last_edited_by",
    "last_edited_at",
}
ENTRIES_URL = "/api/key-value-table-entries/"


def _table_url(table) -> str:
    return reverse("key-value-tables-detail", args=[table.pk])


def _entry_url(entry) -> str:
    return reverse("key-value-table-entries-detail", args=[entry.pk])


def _runtime_url(session, table, operation: str) -> str:
    return f"/api/internal/sessions/{session.pk}/key-value-tables/{table.pk}/{operation}/"


def _last_edit_of(row) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(row), object_id=row.pk
    ).first()


def _assert_previous_edit_kept(table, editor) -> None:
    assert ResourceLastEdit.objects.count() == 1
    last_edit = _last_edit_of(table)
    assert last_edit.edited_by_id == editor.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


def _rows(body):
    return body["results"] if isinstance(body, dict) else body


@pytest.fixture
def named_admin(admin_acme):
    admin_acme.display_name = "Acme Table Admin"
    admin_acme.save(update_fields=["display_name"])
    return admin_acme


@pytest.fixture
def colleague(db, django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="key-value-colleague@example.com", password="StrongPass123!"
    )
    user.display_name = "Acme Table Colleague"
    user.save(update_fields=["display_name"])
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def client_in(client_as):
    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


@pytest.fixture
def colleague_client(client_in, colleague, acme):
    return client_in(colleague, acme)


@pytest.fixture
def edited_table(acme, named_admin):
    """A table the admin created and last edited a day ago."""
    table = KeyValueTable.objects.create(
        org=acme, name="Customers", description="People", created_by=named_admin
    )
    record_last_edit(table, named_admin, edited_at=PREVIOUS_EDIT_AT)
    return table


@pytest.fixture
def entry(edited_table):
    return KeyValueTableEntry.objects.create(table=edited_table, key="customer_1", value={"a": 1})


@pytest.fixture
def system_client(api_client, env_api_key):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    return api_client


@pytest.fixture
def running_session(acme, edited_table):
    graph = Graph.objects.create(name="Writer flow", org=acme)
    KeyValueNode.objects.create(graph=graph, node_name="write", key_value_table=edited_table)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


# ---- the table's own fields ----


@pytest.mark.django_db
class TestTableAuthorship:
    def test_create_records_the_caller_as_author_and_last_editor(
        self, client_in, named_admin, member_only, acme
    ):
        before = timezone.now()

        response = client_in(named_admin, acme).post(
            reverse("key-value-tables-list"),
            {"name": "Orders", "description": "d", "created_by": member_only.id},
            format="json",
        )

        after = timezone.now()
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert set(body) == TABLE_KEYS
        assert body["created_by"] == expected_user_summary(named_admin)
        assert body["last_edited_by"] == expected_user_summary(named_admin)
        assert before <= parse_datetime(body["created_at"]) <= after
        assert before <= parse_datetime(body["last_edited_at"]) <= after
        assert body["entry_count"] == 0
        assert named_admin.email not in response.content.decode()
        table = KeyValueTable.objects.get(pk=body["id"])
        assert table.created_by_id == named_admin.id
        assert _last_edit_of(table).edited_by_id == named_admin.id

    def test_detail_and_list_render_user_summaries(
        self, client_in, named_admin, member_only, acme, edited_table
    ):
        KeyValueTableEntry.objects.create(table=edited_table, key="k", value=1)
        client = client_in(member_only, acme)

        detail = client.get(_table_url(edited_table))
        listing = client.get(reverse("key-value-tables-list"))

        assert detail.status_code == status.HTTP_200_OK, detail.content
        assert listing.status_code == status.HTTP_200_OK, listing.content
        listed = next(row for row in _rows(listing.json()) if row["id"] == edited_table.pk)
        for body in (detail.json(), listed):
            assert set(body) == TABLE_KEYS
            assert set(body["created_by"]) == USER_SUMMARY_KEYS
            assert body["created_by"] == expected_user_summary(named_admin)
            assert body["last_edited_by"] == expected_user_summary(named_admin)
            assert parse_datetime(body["created_at"]) == edited_table.created_at
            assert parse_datetime(body["last_edited_at"]) == PREVIOUS_EDIT_AT
            assert body["entry_count"] == 1
        assert named_admin.email not in detail.content.decode() + listing.content.decode()

    def test_table_without_author_or_last_edit_renders_nulls(self, client_in, named_admin, acme):
        table = KeyValueTable.objects.create(org=acme, name="Ownerless")

        body = client_in(named_admin, acme).get(_table_url(table)).json()

        assert body["created_by"] is None
        assert body["last_edited_by"] is None
        assert body["last_edited_at"] is None

    @pytest.mark.parametrize(
        "change",
        [{"name": "Clients"}, {"description": "Paying customers"}],
        ids=["rename", "description"],
    )
    def test_edit_by_colleague_replaces_last_edit_and_keeps_author(
        self, colleague_client, colleague, named_admin, edited_table, change
    ):
        response = colleague_client.patch(_table_url(edited_table), change, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["created_by"] == expected_user_summary(named_admin)
        assert body["last_edited_by"] == expected_user_summary(colleague)
        last_edit = _last_edit_of(edited_table)
        assert last_edit.edited_by_id == colleague.id
        assert last_edit.edited_at > PREVIOUS_EDIT_AT
        edited_table.refresh_from_db()
        assert edited_table.created_by_id == named_admin.id

    def test_edit_of_table_without_author_does_not_make_the_editor_its_author(
        self, colleague_client, colleague, acme
    ):
        table = KeyValueTable.objects.create(org=acme, name="Ownerless")

        response = colleague_client.patch(_table_url(table), {"name": "Claimed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["created_by"] is None
        table.refresh_from_db()
        assert table.created_by_id is None
        assert _last_edit_of(table).edited_by_id == colleague.id

    def test_save_without_change_records_nothing(self, colleague_client, named_admin, edited_table):
        response = colleague_client.put(
            _table_url(edited_table),
            {"name": "Customers", "description": "People", "created_at": "2001-01-01T00:00:00Z"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["last_edited_by"] == expected_user_summary(named_admin)
        _assert_previous_edit_kept(edited_table, named_admin)


# ---- entries edited by a user are edits of their table ----


@pytest.mark.django_db
class TestEntryEditsAreTableEdits:
    def test_adding_an_entry_records_a_last_edit_of_the_table(
        self, colleague_client, colleague, edited_table
    ):
        response = colleague_client.post(
            ENTRIES_URL, {"table": edited_table.pk, "key": "customer_2", "value": 2}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert ResourceLastEdit.objects.count() == 1
        last_edit = _last_edit_of(edited_table)
        assert last_edit.edited_by_id == colleague.id
        assert last_edit.edited_at > PREVIOUS_EDIT_AT

    @pytest.mark.parametrize(
        "change", [{"value": [1, 2]}, {"key": "customer_renamed"}], ids=["value", "key"]
    )
    def test_editing_an_entry_records_a_last_edit_of_the_table(
        self, colleague_client, colleague, edited_table, entry, change
    ):
        response = colleague_client.patch(_entry_url(entry), change, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert ResourceLastEdit.objects.count() == 1
        assert _last_edit_of(edited_table).edited_by_id == colleague.id

    def test_deleting_an_entry_records_a_last_edit_of_the_table(
        self, colleague_client, colleague, edited_table, entry
    ):
        response = colleague_client.delete(_entry_url(entry))

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        assert ResourceLastEdit.objects.count() == 1
        assert _last_edit_of(edited_table).edited_by_id == colleague.id

    def test_table_detail_shows_the_entry_editor(
        self, colleague_client, colleague, named_admin, edited_table, entry
    ):
        colleague_client.patch(_entry_url(entry), {"value": 5}, format="json")

        body = colleague_client.get(_table_url(edited_table)).json()

        assert body["created_by"] == expected_user_summary(named_admin)
        assert body["last_edited_by"] == expected_user_summary(colleague)

    def test_saving_an_entry_without_change_records_nothing(
        self, colleague_client, named_admin, edited_table, entry
    ):
        response = colleague_client.put(
            _entry_url(entry),
            {"table": edited_table.pk, "key": "customer_1", "value": {"a": 1}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        _assert_previous_edit_kept(edited_table, named_admin)

    def test_saving_a_flow_written_entry_unchanged_records_nothing(
        self, colleague_client, named_admin, edited_table, entry, running_session
    ):
        # The hand save clears the run attribution, which alone is no edit of the table.
        entry.updated_by_session = running_session
        entry.save(update_fields=["updated_by_session"])

        response = colleague_client.patch(_entry_url(entry), {"value": {"a": 1}}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["updated_by_session"] is None
        _assert_previous_edit_kept(edited_table, named_admin)

    def test_rejected_entry_write_records_nothing(
        self, colleague_client, named_admin, edited_table, entry
    ):
        KeyValueTableEntry.objects.create(table=edited_table, key="taken", value=0)

        response = colleague_client.patch(_entry_url(entry), {"key": "taken"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        _assert_previous_edit_kept(edited_table, named_admin)


# ---- flow runs write values, which is no edit ----


@pytest.mark.django_db
class TestRuntimeWritesRecordNothing:
    @pytest.mark.parametrize(
        ("operation", "payload"),
        [
            ("write", {"entries": {"customer_1": {"a": 2}, "customer_9": 9}}),
            ("delete", {"keys": ["customer_1"]}),
        ],
        ids=["write", "delete"],
    )
    def test_runtime_change_keeps_the_last_user_edit(
        self, system_client, running_session, named_admin, edited_table, entry, operation, payload
    ):
        response = system_client.post(
            _runtime_url(running_session, edited_table, operation), payload, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        _assert_previous_edit_kept(edited_table, named_admin)

    def test_runtime_write_to_never_edited_table_records_no_null_editor(self, system_client, acme):
        table = KeyValueTable.objects.create(org=acme, name="Run only")
        graph = Graph.objects.create(name="Run only flow", org=acme)
        KeyValueNode.objects.create(graph=graph, node_name="write", key_value_table=table)
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)

        response = system_client.post(
            _runtime_url(session, table, "write"), {"entries": {"k": 1}}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert KeyValueTableEntry.objects.filter(table=table, key="k").exists()
        assert not ResourceLastEdit.objects.exists()


# ---- organization scoping ----


@pytest.mark.django_db
class TestOtherOrganization:
    @pytest.fixture
    def beta_table(self, beta):
        return KeyValueTable.objects.create(org=beta, name="Theirs")

    def test_table_of_other_org_is_404_and_records_no_edit(
        self, client_in, named_admin, acme, beta_table
    ):
        client = client_in(named_admin, acme)

        detail = client.get(_table_url(beta_table))
        patched = client.patch(_table_url(beta_table), {"name": "hijacked"}, format="json")

        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert patched.status_code == status.HTTP_404_NOT_FOUND
        beta_table.refresh_from_db()
        assert beta_table.name == "Theirs"
        assert _last_edit_of(beta_table) is None

    @pytest.mark.parametrize("method", ["patch", "delete"])
    def test_entry_of_other_org_is_404_and_records_no_edit(
        self, client_in, named_admin, acme, beta_table, method
    ):
        beta_entry = KeyValueTableEntry.objects.create(table=beta_table, key="k", value=1)

        response = getattr(client_in(named_admin, acme), method)(
            _entry_url(beta_entry), {"value": 2}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert KeyValueTableEntry.objects.filter(pk=beta_entry.pk, value=1).exists()
        assert _last_edit_of(beta_table) is None

    def test_entry_into_other_org_table_is_rejected_and_records_no_edit(
        self, client_in, named_admin, acme, beta_table
    ):
        response = client_in(named_admin, acme).post(
            ENTRIES_URL, {"table": beta_table.pk, "key": "k", "value": 1}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not KeyValueTableEntry.objects.filter(table=beta_table).exists()
        assert _last_edit_of(beta_table) is None
