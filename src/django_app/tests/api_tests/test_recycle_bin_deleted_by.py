"""Who deleted a recycle-bin item: recorded on delete as the item's last edit (a binned item
can't be edited), and shown with its author as the first two detail lines of every bin tab."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from agents.models import AgentDefinition, Surface
from rbac.authorship import record_last_edit
from rbac.governance.authorship import AuthorshipReleaseService
from rbac.governance.memberships import MembershipManagementService
from rbac.models import LastEditTrackedModel, OrganizationUser, ResourceLastEdit
from tables.models import Graph, PythonCode, PythonCodeTool, StorageFile
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.storage_service.manager import StorageManager
from tests.api_tests.recycle_bin_cases import AGENTS_URL, CASES, FLOWS_URL, SURFACES_URL
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from tests.user_summary_helpers import expected_user_summary

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("retention_seven_days")]

STORAGE_BIN_URL = "/api/storage/recycle-bin/"
CREATED_BY = "Created by"
DELETED_BY = "Deleted by"
EDITED_BEFORE = timezone.now() - timedelta(days=1)


@pytest.fixture
def author(django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(
        email="bin-author@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.fixture
def second_admin(django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="bin-second-admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def real_manager():
    storage_manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=storage_manager):
        yield storage_manager


def _client_in(client_as, user, org) -> APIClient:
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _bin(client, list_url) -> list[dict]:
    response = client.get(f"{list_url}recycle-bin/")
    assert response.status_code == 200, response.content
    return response.json()["results"]


def _authorship_lines(entry: dict) -> list[dict]:
    return entry["details"][:2]


def _user_line(label: str, user) -> dict:
    return {
        "label": label,
        "value": expected_user_summary(user) if user is not None else None,
        "format": "user",
    }


def _last_edit_of(row) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(row), object_id=row.pk
    ).first()


def _deleter_id(row) -> int | None:
    """The deleter recorded on a binned row: its last edit, at its deletion time."""
    last_edit = _last_edit_of(row)
    stored = type(row).all_objects.get(pk=row.pk)
    assert last_edit is not None
    assert last_edit.edited_at == stored.soft_deleted_at
    return last_edit.edited_by_id


def _make(case, org, author=None, suffix=""):
    row = case.make(org, f"deleted-by-{case.key}{suffix}")
    if author is not None:
        case.model.all_objects.filter(pk=row.pk).update(created_by=author)
    return row


def test_every_bin_resource_records_last_edits():
    # The deleter is stored as the last edit, which a purge removes through the
    # model's `last_edits` relation.
    for resource in bin_resources().values():
        assert issubclass(resource.model, LastEditTrackedModel), resource.model
    assert issubclass(StorageFile, LastEditTrackedModel)


@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
class TestEveryBinResource:
    def test_delete_records_the_request_user_and_both_lines_come_first(
        self, case, acme_admin_client, admin_acme, author, acme
    ):
        row = _make(case, acme, author)

        assert acme_admin_client.delete(f"{case.url}{row.pk}/").status_code == case.delete_status

        assert _deleter_id(row) == admin_acme.pk
        assert _authorship_lines(_bin(acme_admin_client, case.url)[0]) == [
            _user_line(CREATED_BY, author),
            _user_line(DELETED_BY, admin_acme),
        ]

    def test_restore_keeps_the_deleter_as_last_editor(self, case, acme_admin_client, admin_acme, acme):
        row = _make(case, acme)
        acme_admin_client.delete(f"{case.url}{row.pk}/")

        assert acme_admin_client.post(f"{case.url}{row.pk}/restore/").status_code == 200

        assert _last_edit_of(row).edited_by_id == admin_acme.pk

    def test_bulk_restore_keeps_the_deleter_as_last_editor(
        self, case, acme_admin_client, admin_acme, acme
    ):
        row = _make(case, acme)
        acme_admin_client.delete(f"{case.url}{row.pk}/")

        response = acme_admin_client.post(
            f"{case.url}recycle-bin/restore/", {"ids": [row.pk]}, format="json"
        )

        assert response.status_code == 200, response.content
        assert _last_edit_of(row).edited_by_id == admin_acme.pk

    def test_purge_removes_the_record(self, case, acme_admin_client, superadmin_in_acme, acme):
        row = _make(case, acme)
        acme_admin_client.delete(f"{case.url}{row.pk}/")

        assert superadmin_in_acme.delete(f"{case.url}{row.pk}/purge/").status_code == 204

        assert _last_edit_of(row) is None

    def test_bulk_purge_and_emptying_the_bin_remove_the_records(
        self, case, acme_admin_client, superadmin_in_acme, acme
    ):
        selected = _make(case, acme, suffix="-selected")
        rest = _make(case, acme, suffix="-rest")
        for row in (selected, rest):
            acme_admin_client.delete(f"{case.url}{row.pk}/")

        by_id = superadmin_in_acme.post(
            f"{case.url}recycle-bin/purge/", {"ids": [selected.pk]}, format="json"
        )
        everything = superadmin_in_acme.post(
            f"{case.url}recycle-bin/purge/", {"all": True}, format="json"
        )

        assert (by_id.status_code, everything.status_code) == (200, 200)
        assert _last_edit_of(selected) is None
        assert _last_edit_of(rest) is None

    def test_an_item_binned_without_a_record_shows_null(self, case, acme_admin_client, author, acme):
        # Items binned before deleters were recorded: a last edit from before the
        # delete names an editor, not the deleter.
        row = _make(case, acme)
        record_last_edit(row, author, edited_at=EDITED_BEFORE)
        row.delete()

        assert _authorship_lines(_bin(acme_admin_client, case.url)[0]) == [
            _user_line(CREATED_BY, None),
            _user_line(DELETED_BY, None),
        ]

    def test_another_orgs_restore_or_purge_leaves_the_record(
        self, case, client_as, django_user_model, beta, role_org_admin, acme_admin_client, superadmin_in_acme
    ):
        beta_admin = django_user_model.objects.create_user(
            email="bin-beta-admin@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=beta_admin, org=beta, role=role_org_admin)
        row = _make(case, beta)
        _client_in(client_as, beta_admin, beta).delete(f"{case.url}{row.pk}/")

        assert acme_admin_client.post(f"{case.url}{row.pk}/restore/").status_code == 404
        assert superadmin_in_acme.delete(f"{case.url}{row.pk}/purge/").status_code == 404
        assert _bin(acme_admin_client, case.url) == []
        assert _deleter_id(row) == beta_admin.pk


def test_restore_shows_the_deleter_as_last_editor(acme_admin_client, admin_acme, author, acme):
    graph = Graph.objects.create(org=acme, name="Comes back")
    record_last_edit(graph, author, edited_at=EDITED_BEFORE)
    acme_admin_client.delete(f"{FLOWS_URL}{graph.pk}/")

    acme_admin_client.post(f"{FLOWS_URL}{graph.pk}/restore/")

    response = acme_admin_client.get(f"{FLOWS_URL}{graph.pk}/")
    assert response.json()["last_edited_by"] == expected_user_summary(admin_acme)


def test_emptying_every_bin_removes_the_records(acme_admin_client, superadmin_in_acme, acme):
    graph = Graph.objects.create(org=acme, name="Emptied")
    acme_admin_client.delete(f"{FLOWS_URL}{graph.pk}/")

    response = superadmin_in_acme.post("/api/recycle-bin/empty/")

    assert response.status_code == 200, response.content
    assert _last_edit_of(graph) is None


def test_the_scheduled_purge_removes_the_record(acme_admin_client, acme):
    graph = Graph.objects.create(org=acme, name="Expired")
    acme_admin_client.delete(f"{FLOWS_URL}{graph.pk}/")

    PurgeService.purge_expired(now=timezone.now() + timedelta(days=8))

    assert not Graph.all_objects.filter(pk=graph.pk).exists()
    assert _last_edit_of(graph) is None


def test_a_delete_without_a_person_records_no_deleter(issue_api_key, author, acme, acme_admin_client):
    graph = Graph.objects.create(org=acme, name="System deleted")
    record_last_edit(graph, author, edited_at=EDITED_BEFORE)
    raw_key, _ = issue_api_key(user=None)
    system_client = APIClient()
    system_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

    assert system_client.delete(f"{FLOWS_URL}{graph.pk}/").status_code == 204

    assert _deleter_id(graph) is None
    assert _authorship_lines(_bin(acme_admin_client, FLOWS_URL)[0])[1] == _user_line(DELETED_BY, None)


def test_a_management_command_delete_replaces_the_previous_editor(author, acme):
    graph = Graph.objects.create(org=acme, name="Command deleted")
    record_last_edit(graph, author, edited_at=EDITED_BEFORE)

    move_to_recycle_bin(graph, None)

    # Otherwise "Deleted by" (and, after a restore, "Last edited by") would name the
    # previous editor as if they had deleted it.
    assert _deleter_id(graph) is None


def test_a_built_in_tool_records_no_deleter(admin_acme):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    built_in = PythonCodeTool.objects.create(
        name="Built-in deleted", description="d", python_code=code, built_in=True
    )

    move_to_recycle_bin(built_in, admin_acme)

    # Shared by every organization: no org's user is recorded on it.
    assert _last_edit_of(built_in) is None


def test_deleting_an_already_binned_item_keeps_the_first_record(
    acme_admin_client, admin_acme, second_admin, acme
):
    graph = Graph.objects.create(org=acme, name="Twice")
    stale_copy = Graph.objects.get(pk=graph.pk)
    acme_admin_client.delete(f"{FLOWS_URL}{graph.pk}/")
    first = _last_edit_of(graph)

    assert move_to_recycle_bin(stale_copy, second_admin) is None

    again = _last_edit_of(graph)
    assert (again.edited_by_id, again.edited_at) == (admin_acme.pk, first.edited_at)


def test_a_deleted_user_shows_as_null(client_as, second_admin, acme_admin_client, acme):
    graph = Graph.objects.create(org=acme, name="Orphaned", created_by=second_admin)
    _client_in(client_as, second_admin, acme).delete(f"{FLOWS_URL}{graph.pk}/")

    second_admin.delete()

    assert _authorship_lines(_bin(acme_admin_client, FLOWS_URL)[0]) == [
        _user_line(CREATED_BY, None),
        _user_line(DELETED_BY, None),
    ]


def test_a_deleter_who_left_the_org_shows_as_null(
    client_as, second_admin, superadmin, acme_admin_client, acme
):
    graph = Graph.objects.create(org=acme, name="Left behind", created_by=second_admin)
    _client_in(client_as, second_admin, acme).delete(f"{FLOWS_URL}{graph.pk}/")
    membership = OrganizationUser.objects.get(user=second_admin, org=acme)

    MembershipManagementService().remove_member(superadmin, membership.pk)

    assert _deleter_id(graph) is None
    assert _authorship_lines(_bin(acme_admin_client, FLOWS_URL)[0]) == [
        _user_line(CREATED_BY, None),
        _user_line(DELETED_BY, None),
    ]


def test_leaving_one_org_keeps_the_deleter_in_another(second_admin, acme, beta):
    acme_graph = Graph.objects.create(org=acme, name="Acme")
    beta_graph = Graph.objects.create(org=beta, name="Beta")
    for graph in (acme_graph, beta_graph):
        move_to_recycle_bin(graph, second_admin)

    released = AuthorshipReleaseService().release(user_id=second_admin.pk, org_id=acme.id)

    assert released == 1
    assert _deleter_id(acme_graph) is None
    assert _deleter_id(beta_graph) == second_admin.pk


def test_leaving_the_org_releases_a_binned_secrets_deleter(second_admin, acme):
    # Secret became a LastEditTrackedModel for the deleter: the last-edit release covers it.
    secret = CASES[[case.key for case in CASES].index("secret")].make(acme, "released-secret")
    move_to_recycle_bin(secret, second_admin)

    AuthorshipReleaseService().release(user_id=second_admin.pk, org_id=acme.id)

    assert _deleter_id(secret) is None


def test_losing_superadmin_releases_deleters_outside_memberships(superadmin, acme):
    graph = Graph.objects.create(org=acme, name="Superadmin deleted")
    move_to_recycle_bin(graph, superadmin)

    released = AuthorshipReleaseService().release_outside_memberships(user_id=superadmin.pk)

    assert released == 1
    assert _deleter_id(graph) is None


def test_avatar_urls_are_absolute(acme_admin_client, admin_acme, acme):
    admin_acme.avatar = "avatars/admin.png"
    admin_acme.save(update_fields=["avatar"])
    graph = Graph.objects.create(org=acme, name="Pictured", created_by=admin_acme)
    acme_admin_client.delete(f"{FLOWS_URL}{graph.pk}/")

    lines = _authorship_lines(_bin(acme_admin_client, FLOWS_URL)[0])

    for line in lines:
        assert line["value"]["avatar_url"].startswith("http://testserver/")


def test_a_surface_deleted_with_its_agent_shows_the_agents_deleter(
    acme_admin_client, admin_acme, author, acme
):
    agent = AgentDefinition.objects.create(
        org=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
    )
    surface = Surface.objects.create(org=acme, name="Owned", owner_agent=agent)
    record_last_edit(surface, author, edited_at=EDITED_BEFORE)

    acme_admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

    # Only the item the user picked records the deletion; the surface keeps its editor.
    assert _last_edit_of(surface).edited_by_id == author.pk
    entry = _bin(acme_admin_client, SURFACES_URL)[0]
    assert entry["id"] == surface.pk
    assert _authorship_lines(entry)[1] == _user_line(DELETED_BY, admin_acme)


def test_a_surface_deleted_before_its_agent_keeps_its_own_deleter(
    acme_admin_client, client_as, second_admin, acme
):
    agent = AgentDefinition.objects.create(
        org=acme, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
    )
    surface = Surface.objects.create(org=acme, name="Owned", owner_agent=agent)
    _client_in(client_as, second_admin, acme).delete(f"{SURFACES_URL}{surface.pk}/")

    acme_admin_client.delete(f"{AGENTS_URL}{agent.pk}/")

    entry = _bin(acme_admin_client, SURFACES_URL)[0]
    assert _authorship_lines(entry)[1] == _user_line(DELETED_BY, second_admin)


def _make_tool(org, name):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(name=name, description="d", python_code=code, org=org)


def test_bulk_deletes_record_the_request_user(acme_admin_client, admin_acme, acme):
    python_tool = _make_tool(acme, "Bulk python")
    mcp_tool = McpTool.objects.create(
        name="Bulk mcp", org=acme, transport="https://example.com/mcp", tool_name="t"
    )
    collection = CASES[[case.key for case in CASES].index("collection")].make(acme, "Bulk docs")

    responses = [
        acme_admin_client.post("/api/python-code-tool/bulk-delete/", {"ids": [python_tool.pk]}, format="json"),
        acme_admin_client.post("/api/mcp-tools/bulk-delete/", {"ids": [mcp_tool.pk]}, format="json"),
        acme_admin_client.post(
            "/api/source-collections/bulk-delete/",
            {"collection_ids": [collection.pk]},
            format="json",
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    for row in (python_tool, mcp_tool, collection):
        assert _deleter_id(row) == admin_acme.pk


def test_the_list_reads_users_once_whatever_the_number_of_entries(
    acme_admin_client, django_user_model, acme, role_org_admin, client_as, django_assert_num_queries
):
    def bin_graphs(count, offset):
        for index in range(count):
            user = django_user_model.objects.create_user(
                email=f"bin-n1-{offset + index}@example.com", password="StrongPass123!"
            )
            OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
            graph = Graph.objects.create(org=acme, name=f"N+1 {offset + index}", created_by=user)
            _client_in(client_as, user, acme).delete(f"{FLOWS_URL}{graph.pk}/")

    bin_graphs(1, offset=0)
    _bin(acme_admin_client, FLOWS_URL)  # warms the per-process caches (content types, roles)
    with CaptureQueriesContext(connection) as one_entry:
        _bin(acme_admin_client, FLOWS_URL)
    # captured_queries reads the connection's log when accessed: count before more queries run.
    one_entry_queries = len(one_entry.captured_queries)
    bin_graphs(4, offset=1)

    with django_assert_num_queries(one_entry_queries):
        entries = _bin(acme_admin_client, FLOWS_URL)

    assert len(entries) == 5
    assert all(entry["details"][1]["value"] is not None for entry in entries)


class TestStorageBin:
    def test_delete_records_the_request_user_and_both_lines_come_first(
        self, acme_admin_client, admin_acme, author, real_manager, acme
    ):
        seed_file(real_manager._backend, acme.id, "docs/a.txt", b"a")
        StorageFile.objects.filter(org=acme).update(created_by=author)

        response = acme_admin_client.delete("/api/storage/delete/", {"paths": ["docs/"]}, format="json")

        assert response.status_code == 204, response.content
        folder = StorageFile.deleted_objects.get(org=acme, path="docs/")
        file_row = StorageFile.deleted_objects.get(org=acme, path="docs/a.txt")
        assert _deleter_id(folder) == admin_acme.pk
        # Deleted with its folder, not an entry: no deletion recorded on it.
        assert _last_edit_of(file_row) is None
        entry = acme_admin_client.get(STORAGE_BIN_URL).json()["results"][0]
        assert entry["details"][:2] == [
            _user_line(CREATED_BY, author),
            _user_line(DELETED_BY, admin_acme),
        ]

    def test_restore_keeps_the_deleter_and_purge_removes_it(
        self, acme_admin_client, superadmin_in_acme, admin_acme, real_manager, acme
    ):
        for path in ("keep.txt", "drop.txt"):
            seed_file(real_manager._backend, acme.id, path, b"x")
        acme_admin_client.delete(
            "/api/storage/delete/", {"paths": ["keep.txt", "drop.txt"]}, format="json"
        )
        kept = StorageFile.deleted_objects.get(org=acme, path="keep.txt")
        dropped = StorageFile.deleted_objects.get(org=acme, path="drop.txt")

        restored = acme_admin_client.post(f"{STORAGE_BIN_URL}restore/", {"ids": [kept.pk]}, format="json")
        purged = superadmin_in_acme.post(
            f"{STORAGE_BIN_URL}purge/", {"ids": [dropped.pk]}, format="json"
        )

        assert (restored.status_code, purged.status_code) == (200, 200)
        assert _last_edit_of(kept).edited_by_id == admin_acme.pk
        assert _last_edit_of(dropped) is None

    def test_a_file_binned_without_a_record_shows_null(self, acme_admin_client, real_manager, acme):
        seed_file(real_manager._backend, acme.id, "old.txt", b"x")
        real_manager.delete(acme.id, "old.txt", user=None)
        row = StorageFile.deleted_objects.get(org=acme, path="old.txt")
        _last_edit_of(row).delete()

        entry = acme_admin_client.get(STORAGE_BIN_URL).json()["results"][0]

        assert entry["details"][:2] == [_user_line(CREATED_BY, None), _user_line(DELETED_BY, None)]
