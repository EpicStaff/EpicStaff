import io
import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import serializers, status

from rbac.models import OrganizationUser
from tables.models import Graph, StorageFile
from tables.services import redis_pubsub
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.path_utils import storage_key
from tables.services.storage_service.reconciler import StorageReconciler
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from tests.storage_tests.storage_writes import store_object, stream_upload
from tests.user_summary_helpers import expected_user_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def manager(backend):
    return StorageManager(backend)


@pytest.fixture(autouse=True)
def view_manager(manager):
    with patch("tables.views.storage_views.get_storage_manager", return_value=manager):
        yield manager


@pytest.fixture
def client_in_org(client_as):
    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


def _author_id(org, path: str) -> int | None:
    return StorageFile.objects.values_list("created_by_id", flat=True).get(org=org, path=path)


@sync_to_async
def _author_id_async(org, path: str) -> int | None:
    return _author_id(org, path)


@sync_to_async
def _last_editor_id_async(org, path: str) -> int | None:
    file_row = StorageFile.objects.get(org=org, path=path)
    return file_row.last_edits.get().edited_by_id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("stream_backend")
class TestUpload:
    async def test_upload_authors_file_and_new_ancestor_folders(self, admin_acme, acme):
        response = await stream_upload(admin_acme, acme, "a/b", "report.txt")

        assert response.status_code == 200, response.text
        assert await _author_id_async(acme, "a/b/report.txt") == admin_acme.id
        assert await _author_id_async(acme, "a/") == admin_acme.id
        assert await _author_id_async(acme, "a/b/") == admin_acme.id

    async def test_upload_into_existing_folder_leaves_folder_author(
        self, manager, admin_acme, acme
    ):
        await sync_to_async(manager.mkdir)(acme.id, "shared")

        response = await stream_upload(admin_acme, acme, "shared", "report.txt")

        assert response.status_code == 200, response.text
        assert await _author_id_async(acme, "shared/") is None
        assert await _author_id_async(acme, "shared/report.txt") == admin_acme.id

    async def test_reupload_by_another_user_keeps_author(
        self, backend, admin_acme, member_only, acme
    ):
        await sync_to_async(store_object)(
            backend, acme.id, "report.txt", b"first", user=admin_acme
        )

        response = await stream_upload(member_only, acme, "", "report.txt", b"second!")

        assert response.status_code == 200, response.text
        row = await StorageFile.objects.aget(org=acme, path="report.txt")
        assert row.created_by_id == admin_acme.id
        assert row.size == len(b"second!")

    async def test_reupload_over_unauthored_file_leaves_it_unauthored(
        self, backend, member_only, acme
    ):
        await sync_to_async(store_object)(backend, acme.id, "report.txt", b"system")

        response = await stream_upload(member_only, acme, "", "report.txt")

        assert response.status_code == 200, response.text
        assert await _author_id_async(acme, "report.txt") is None

    async def test_archive_upload_authors_every_extracted_row(self, admin_acme, acme, sample_zip):
        response = await stream_upload(admin_acme, acme, "", "bundle.zip", sample_zip.read())

        assert response.status_code == 200, response.text
        rows = StorageFile.objects.filter(org=acme, path__startswith="bundle/")
        authors = {path: author async for path, author in rows.values_list("path", "created_by_id")}
        assert set(authors) == {
            "bundle/",
            "bundle/hello.txt",
            "bundle/sub/",
            "bundle/sub/world.txt",
        }
        assert set(authors.values()) == {admin_acme.id}

    async def test_archive_upload_authors_and_records_an_empty_folder(self, admin_acme, acme):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive_file:
            archive_file.writestr("a.txt", b"a")
            archive_file.writestr(zipfile.ZipInfo("empty/"), b"")
        archive = buffer.getvalue()

        response = await stream_upload(admin_acme, acme, "", "bundle.zip", archive)

        assert response.status_code == 200, response.text
        assert await _author_id_async(acme, "bundle/empty/") == admin_acme.id
        assert await _last_editor_id_async(acme, "bundle/empty/") == admin_acme.id

    async def test_upload_with_the_system_api_key_has_no_author_and_a_null_editor(
        self, issue_api_key, acme
    ):
        raw_key, _ = await sync_to_async(issue_api_key)(user=None, name="storage-system-key")

        response = await stream_upload(None, acme, "", "report.txt", api_key=raw_key)

        assert response.status_code == 200, response.text
        assert await _author_id_async(acme, "report.txt") is None
        assert await _last_editor_id_async(acme, "report.txt") is None


class TestMkdir:
    def test_mkdir_authors_folder_and_new_ancestors(self, client_in_org, member_only, acme):
        response = client_in_org(member_only, acme).post(
            "/api/storage/mkdir/", {"path": "projects/alpha"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "projects/alpha/") == member_only.id
        assert _author_id(acme, "projects/") == member_only.id


class TestCopy:
    def test_copy_authors_every_new_row_by_actor(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "docs", user=admin_acme)
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/copy/",
            {"from_path": "docs", "to_path": "backup"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        copied = StorageFile.objects.filter(org=acme, path__startswith="backup/")
        assert set(copied.values_list("path", flat=True)) == {
            "backup/",
            "backup/docs/",
            "backup/docs/a.txt",
        }
        assert set(copied.values_list("created_by_id", flat=True)) == {member_only.id}
        assert _author_id(acme, "docs/a.txt") == admin_acme.id

    def test_copy_onto_an_existing_row_keeps_its_author(
        self, backend, client_in_org, admin_acme, member_only, acme
    ):
        # A row whose object is gone: the copy lands on its path again.
        StorageFile.objects.create(
            org=acme, path="backup/a.txt", name="a.txt", size=1, created_by=admin_acme
        )
        store_object(backend, acme.id, "a.txt", b"copied", user=admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/copy/", {"from_path": "a.txt", "to_path": "backup"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        row = StorageFile.objects.get(org=acme, path="backup/a.txt")
        assert row.created_by_id == admin_acme.id
        assert row.size == len(b"copied")


class TestRenameAndMove:
    def test_rename_of_unauthored_file_leaves_it_unauthored(
        self, backend, client_in_org, manager, member_only, acme
    ):
        store_object(backend, acme.id, "draft.txt", b"x")

        response = client_in_org(member_only, acme).post(
            "/api/storage/rename/",
            {"from_path": "draft.txt", "to_path": "final.txt"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "final.txt") is None

    def test_rename_of_authored_file_keeps_author(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        store_object(backend, acme.id, "draft.txt", b"x", user=admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/rename/",
            {"from_path": "draft.txt", "to_path": "final.txt"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "final.txt") == admin_acme.id

    def test_move_of_folder_leaves_unauthored_rows_unauthored(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "archive", user=admin_acme)
        manager.mkdir(acme.id, "docs")
        manager.mkdir(acme.id, "docs/nested")
        store_object(backend, acme.id, "docs/a.txt", b"a")

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/",
            {"from_path": "docs", "to_path": "archive"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "archive/docs/") is None
        assert _author_id(acme, "archive/docs/nested/") is None
        assert _author_id(acme, "archive/docs/a.txt") is None
        assert _author_id(acme, "archive/") == admin_acme.id

    def test_move_of_unauthored_file_leaves_it_unauthored(
        self, backend, client_in_org, manager, member_only, acme
    ):
        manager.mkdir(acme.id, "archive")
        store_object(backend, acme.id, "report.txt", b"r")

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/",
            {"from_path": "report.txt", "to_path": "archive"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "archive/report.txt") is None
        assert _author_id(acme, "archive/") is None


class TestCrossOrgTransfers:
    def test_cross_org_copy_authors_destination_rows_by_superadmin(
        self, backend, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)

        response = client_in_org(superadmin, acme).post(
            "/api/storage/copy/",
            {
                "from_path": "docs/a.txt",
                "to_path": "inbox",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(beta, "inbox/a.txt") == superadmin.id
        assert _author_id(beta, "inbox/") == superadmin.id
        assert _author_id(acme, "docs/a.txt") == admin_acme.id

    def test_cross_org_move_drops_authors_who_are_not_destination_members(
        self, backend, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        manager.mkdir(acme.id, "docs", user=admin_acme)
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)

        response = client_in_org(superadmin, acme).post(
            "/api/storage/move/",
            {
                "from_path": "docs",
                "to_path": "inbox",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        moved = StorageFile.objects.filter(org=beta)
        # admin_acme is no member of beta, so the moved rows lose their author; the
        # ancestor folder the move created is a new row authored by the mover.
        assert dict(moved.values_list("path", "created_by_id")) == {
            "inbox/": superadmin.id,
            "inbox/docs/": None,
            "inbox/docs/a.txt": None,
        }
        assert not StorageFile.objects.filter(org=acme).exists()


@pytest.fixture
def member_of_both(django_user_model, acme, beta, role_member):
    user = django_user_model.objects.create_user(
        email="member-of-both@example.com", password="StrongPass123!"
    )
    for member_org in (acme, beta):
        OrganizationUser.objects.create(user=user, org=member_org, role=role_member)
    return user


def _authors_in(org) -> dict[str, int | None]:
    return dict(StorageFile.objects.filter(org=org).values_list("path", "created_by_id"))


class TestCrossOrgMoveAuthorship:
    """A cross-org move is not a creation: moved rows keep only authors the destination knows."""

    def test_moved_file_keeps_an_author_who_is_a_destination_member(
        self, backend, manager, superadmin, member_of_both, acme, beta
    ):
        store_object(backend, acme.id, "a.txt", b"a", user=member_of_both)

        manager.move_cross_org(acme.id, "a.txt", beta.id, "", user=superadmin)

        assert _authors_in(beta) == {"a.txt": member_of_both.id}
        assert _authors_in(acme) == {}

    def test_moved_file_loses_an_author_who_is_no_destination_member(
        self, backend, manager, superadmin, member_only, acme, beta
    ):
        store_object(backend, acme.id, "a.txt", b"a", user=member_only)

        manager.move_cross_org(acme.id, "a.txt", beta.id, "", user=superadmin)

        assert _authors_in(beta) == {"a.txt": None}

    def test_moved_unauthored_file_stays_unauthored(self, backend, manager, superadmin, acme, beta):
        store_object(backend, acme.id, "a.txt", b"a")

        manager.move_cross_org(acme.id, "a.txt", beta.id, "", user=superadmin)

        assert _authors_in(beta) == {"a.txt": None}

    def test_moved_file_without_a_source_row_is_unauthored(
        self, backend, manager, superadmin, acme, beta
    ):
        backend.put_bytes(storage_key(acme.id, "untracked.txt"), b"u")

        manager.move_cross_org(acme.id, "untracked.txt", beta.id, "", user=superadmin)

        assert _authors_in(beta) == {"untracked.txt": None}

    def test_mover_authors_only_the_new_ancestor_folders(
        self, backend, manager, superadmin, member_of_both, acme, beta
    ):
        store_object(backend, acme.id, "a.txt", b"a", user=member_of_both)

        manager.move_cross_org(acme.id, "a.txt", beta.id, "inbox/new", user=superadmin)

        assert _authors_in(beta) == {
            "inbox/": superadmin.id,
            "inbox/new/": superadmin.id,
            "inbox/new/a.txt": member_of_both.id,
        }

    def test_existing_destination_file_keeps_its_own_author(
        self, backend, manager, superadmin, member_of_both, admin_acme, acme, beta
    ):
        # A destination row whose object is gone: the copy lands on its path again.
        StorageFile.objects.create(
            org=beta, path="a.txt", name="a.txt", size=1, created_by=member_of_both
        )
        store_object(backend, acme.id, "a.txt", b"moved", user=admin_acme)

        manager.move_cross_org(acme.id, "a.txt", beta.id, "", user=superadmin)

        row = StorageFile.objects.get(org=beta, path="a.txt")
        assert row.created_by_id == member_of_both.id
        assert row.size == len(b"moved")

    def test_folder_move_applies_the_rule_to_every_nested_row(
        self, backend, manager, superadmin, member_of_both, member_only, acme, beta
    ):
        manager.mkdir(acme.id, "docs/sub", user=member_of_both)
        store_object(backend, acme.id, "docs/kept.txt", b"k", user=member_of_both)
        store_object(backend, acme.id, "docs/dropped.txt", b"d", user=member_only)
        store_object(backend, acme.id, "docs/sub/unauthored.txt", b"u")
        StorageFile.objects.filter(org=acme, path="docs/sub/").update(created_by=member_only)

        manager.move_cross_org(acme.id, "docs", beta.id, "inbox", user=superadmin)

        assert _authors_in(beta) == {
            "inbox/": superadmin.id,
            "inbox/docs/": member_of_both.id,
            "inbox/docs/kept.txt": member_of_both.id,
            "inbox/docs/dropped.txt": None,
            "inbox/docs/sub/": None,
            "inbox/docs/sub/unauthored.txt": None,
        }
        assert _authors_in(acme) == {}

    def test_folder_moved_onto_a_taken_name_keeps_the_rule_and_the_existing_folder(
        self, backend, manager, superadmin, member_of_both, member_only, acme, beta
    ):
        manager.mkdir(beta.id, "inbox/docs", user=member_only)
        manager.mkdir(acme.id, "docs", user=member_of_both)
        store_object(backend, acme.id, "docs/a.txt", b"a", user=member_only)

        manager.move_cross_org(acme.id, "docs", beta.id, "inbox", user=superadmin)

        assert _authors_in(beta) == {
            "inbox/": member_only.id,
            "inbox/docs/": member_only.id,
            "inbox/docs (1)/": member_of_both.id,
            "inbox/docs (1)/a.txt": None,
        }

    def test_folder_move_query_count_does_not_grow_with_moved_rows(
        self, backend, manager, superadmin, django_user_model, acme, beta, role_member
    ):
        def folder_with_children(name, child_count):
            for index in range(child_count):
                author = django_user_model.objects.create_user(
                    email=f"{name}-{index}@example.com", password="StrongPass123!"
                )
                for member_org in (acme, beta):
                    OrganizationUser.objects.create(user=author, org=member_org, role=role_member)
                store_object(backend, acme.id, f"{name}/{index}.txt", b"x", user=author)

        def count_move_queries(name):
            with CaptureQueriesContext(connection) as captured:
                manager.move_cross_org(acme.id, name, beta.id, "moved", user=superadmin)
            return len(captured.captured_queries)

        for name, child_count in (("warm-up", 1), ("small", 1), ("large", 4)):
            folder_with_children(name, child_count)
        count_move_queries("warm-up")

        small_count = count_move_queries("small")
        large_count = count_move_queries("large")

        assert small_count == large_count
        moved_authors = {
            path: author
            for path, author in _authors_in(beta).items()
            if path.startswith("moved/large/") and not path.endswith("/")
        }
        assert len(moved_authors) == 4
        assert None not in moved_authors.values()


class TestAddToGraph:
    def test_add_to_graph_authors_a_newly_tracked_row(self, client_in_org, admin_acme, acme):
        graph = Graph.objects.create(name="storage-flow", org=acme)
        info_only_manager = MagicMock()
        info_only_manager.info.return_value = FileInfo(
            id=0,
            name="untracked.txt",
            path="untracked.txt",
            size=1,
            content_type="text/plain",
            modified="2024-01-01T00:00:00Z",
        )

        with patch(
            "tables.views.storage_views.get_storage_manager", return_value=info_only_manager
        ):
            response = client_in_org(admin_acme, acme).post(
                "/api/storage/add-to-graph/",
                {"paths": ["untracked.txt"], "graph_ids": [graph.id]},
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "untracked.txt") == admin_acme.id

    def test_add_to_graph_leaves_tracked_row_author(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        graph = Graph.objects.create(name="storage-flow", org=acme)
        store_object(backend, acme.id, "tracked.txt", b"t", user=member_only)

        response = client_in_org(admin_acme, acme).post(
            "/api/storage/add-to-graph/",
            {"paths": ["tracked.txt"], "graph_ids": [graph.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "tracked.txt") == member_only.id


class TestSystemWritesLeaveAuthorEmpty:
    def test_redis_storage_mutation_creates_unauthored_row(self, monkeypatch, acme):
        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: MagicMock()
        )
        # close_old_connections() would drop the test's transactional connection.
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        message = {
            "data": json.dumps(
                {
                    "execution_id": "exec-1",
                    "org_prefix": f"org_{acme.id}",
                    "mutations": [{"op": "write", "path": f"org_{acme.id}/out/result.txt"}],
                }
            )
        }

        redis_pubsub.RedisPubSub().storage_mutations_handler(message)

        assert _author_id(acme, "out/result.txt") is None
        assert _author_id(acme, "out/") is None

    def test_reconciler_keeps_existing_author_and_creates_unauthored_rows(
        self, backend, admin_acme, acme
    ):
        StorageFile.objects.create(
            org=acme,
            path="docs/a.txt",
            name="a.txt",
            parent_path="docs/",
            size=1,
            created_by=admin_acme,
        )
        backend.put_bytes(f"org_{acme.id}/docs/a.txt", b"grown")
        backend.put_bytes(f"org_{acme.id}/docs/b.txt", b"b")

        StorageReconciler(backend).reconcile_tree(acme.id)

        kept = StorageFile.objects.get(org=acme, path="docs/a.txt")
        assert kept.created_by_id == admin_acme.id
        assert kept.size == len(b"grown")
        assert _author_id(acme, "docs/b.txt") is None
        assert _author_id(acme, "docs/") is None


# ---- listing output ----


def _creation_time(org, path: str) -> str:
    return serializers.DateTimeField().to_representation(
        StorageFile.objects.get(org=org, path=path).created_at
    )


def _assert_authorship(entry: dict, org, path: str, author) -> None:
    assert entry["created_by"] == (expected_user_summary(author) if author else None)
    assert entry["created_at"] == _creation_time(org, path)


@pytest.fixture
def authored_tree(backend, manager, admin_acme, member_only, acme):
    """`docs/` authored by admin_acme, `docs/a.txt` by member_only, `docs/b.txt` by no one."""
    manager.mkdir(acme.id, "docs", user=admin_acme)
    store_object(backend, acme.id, "docs/a.txt", b"a", user=member_only)
    store_object(backend, acme.id, "docs/b.txt", b"b")


class TestListingOutput:
    def test_list_returns_author_and_creation_time_of_each_entry(
        self, client_in_org, authored_tree, admin_acme, member_only, acme
    ):
        client = client_in_org(admin_acme, acme)

        root = client.get("/api/storage/list/", {"path": ""})
        folder = client.get("/api/storage/list/", {"path": "docs"})

        assert root.status_code == status.HTTP_200_OK, root.data
        _assert_authorship(root.data["items"][0], acme, "docs/", admin_acme)
        items = {item["name"]: item for item in folder.data["items"]}
        _assert_authorship(items["a.txt"], acme, "docs/a.txt", member_only)
        _assert_authorship(items["b.txt"], acme, "docs/b.txt", None)

    def test_info_returns_author_and_creation_time_of_file_and_folder(
        self, client_in_org, authored_tree, admin_acme, member_only, acme
    ):
        client = client_in_org(admin_acme, acme)

        file_info = client.get("/api/storage/info/", {"path": "docs/a.txt"})
        folder_info = client.get("/api/storage/info/", {"path": "docs"})

        assert file_info.status_code == status.HTTP_200_OK, file_info.data
        _assert_authorship(file_info.data, acme, "docs/a.txt", member_only)
        _assert_authorship(folder_info.data, acme, "docs/", admin_acme)

    def test_tree_returns_author_of_each_row_and_nulls_for_folders_without_one(
        self, client_in_org, authored_tree, admin_acme, member_only, acme
    ):
        # A row whose parent folder has no row of its own: the tree implies that folder.
        StorageFile.objects.create(
            org=acme, path="loose/c.txt", name="c.txt", parent_path="loose/", created_by=admin_acme
        )

        response = client_in_org(admin_acme, acme).get("/api/storage/tree/", {"path": ""})

        assert response.status_code == status.HTTP_200_OK, response.data
        root = response.data["tree"]
        assert root["created_by"] is None
        assert root["created_at"] is None
        children = {child["name"]: child for child in root["children"]}
        _assert_authorship(children["docs"], acme, "docs/", admin_acme)
        docs_children = {child["name"]: child for child in children["docs"]["children"]}
        _assert_authorship(docs_children["a.txt"], acme, "docs/a.txt", member_only)
        _assert_authorship(docs_children["b.txt"], acme, "docs/b.txt", None)
        implied_folder = children["loose"]
        assert implied_folder["id"] is None
        assert implied_folder["created_by"] is None
        assert implied_folder["created_at"] is None
        _assert_authorship(implied_folder["children"][0], acme, "loose/c.txt", admin_acme)

    def test_search_returns_author_and_creation_time_of_each_result(
        self, client_in_org, authored_tree, admin_acme, member_only, acme
    ):
        response = client_in_org(admin_acme, acme).get("/api/storage/search/", {"q": ".txt"})

        assert response.status_code == status.HTTP_200_OK, response.data
        results = {result["name"]: result for result in response.data["results"]}
        _assert_authorship(results["a.txt"], acme, "docs/a.txt", member_only)
        _assert_authorship(results["b.txt"], acme, "docs/b.txt", None)

    def test_files_by_ids_returns_author_with_absolute_avatar(
        self, client_in_org, authored_tree, admin_acme, member_only, acme
    ):
        member_only.display_name = "Member Only"
        member_only.avatar.name = f"avatars/{member_only.id}/face.png"
        member_only.save(update_fields=["display_name", "avatar"])
        file_row = StorageFile.objects.get(org=acme, path="docs/a.txt")

        response = client_in_org(admin_acme, acme).get(
            "/api/storage/files/", {"ids": str(file_row.id)}
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data[0]["created_by"] == {
            "id": member_only.id,
            "display_name": "Member Only",
            "avatar_url": f"http://testserver/media/avatars/{member_only.id}/face.png",
        }
        assert response.data[0]["created_at"] == _creation_time(acme, "docs/a.txt")

    def test_deleted_author_renders_as_null(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        store_object(backend, acme.id, "orphan.txt", b"o", user=member_only)
        file_row = StorageFile.objects.get(org=acme, path="orphan.txt")
        member_only.delete()
        client = client_in_org(admin_acme, acme)

        listed = client.get("/api/storage/list/", {"path": ""})
        info = client.get("/api/storage/info/", {"path": "orphan.txt"})
        files = client.get("/api/storage/files/", {"ids": str(file_row.id)})

        assert listed.data["items"][0]["created_by"] is None
        assert info.data["created_by"] is None
        assert files.data[0]["created_by"] is None
        assert info.data["created_at"] == _creation_time(acme, "orphan.txt")

    def test_info_of_another_orgs_file_is_not_found(
        self, backend, client_in_org, manager, admin_acme, superadmin, acme, beta
    ):
        store_object(backend, beta.id, "beta-only.txt", b"b", user=superadmin)

        response = client_in_org(admin_acme, acme).get(
            "/api/storage/info/", {"path": "beta-only.txt"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
