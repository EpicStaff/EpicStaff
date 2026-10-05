import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers, status

from tables.models import Graph, StorageFile
from tables.services import redis_pubsub
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.reconciler import StorageReconciler
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
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


def _upload(client, path: str, filename: str, content: bytes = b"data"):
    payload = {"files": SimpleUploadedFile(filename, content, content_type="text/plain")}
    if path:
        payload["path"] = path
    return client.post("/api/storage/upload/", payload)


class TestUpload:
    def test_upload_authors_file_and_new_ancestor_folders(self, client_in_org, admin_acme, acme):
        response = _upload(client_in_org(admin_acme, acme), "a/b", "report.txt")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "a/b/report.txt") == admin_acme.id
        assert _author_id(acme, "a/") == admin_acme.id
        assert _author_id(acme, "a/b/") == admin_acme.id

    def test_upload_into_existing_folder_leaves_folder_author(
        self, client_in_org, manager, admin_acme, acme
    ):
        manager.mkdir(acme.id, "shared")

        response = _upload(client_in_org(admin_acme, acme), "shared", "report.txt")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "shared/") is None
        assert _author_id(acme, "shared/report.txt") == admin_acme.id

    def test_reupload_by_another_user_keeps_author(
        self, client_in_org, admin_acme, member_only, acme
    ):
        _upload(client_in_org(admin_acme, acme), "", "report.txt", b"first")

        response = _upload(client_in_org(member_only, acme), "", "report.txt", b"second!")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        row = StorageFile.objects.get(org=acme, path="report.txt")
        assert row.created_by_id == admin_acme.id
        assert row.size == len(b"second!")

    def test_reupload_over_unauthored_file_claims_it(
        self, client_in_org, manager, member_only, acme
    ):
        manager.upload(acme.id, "report.txt", BytesIO(b"system"))

        response = _upload(client_in_org(member_only, acme), "", "report.txt")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _author_id(acme, "report.txt") == member_only.id

    def test_archive_upload_authors_every_extracted_row(
        self, client_in_org, admin_acme, acme, sample_zip
    ):
        uploaded_file = SimpleUploadedFile(
            "sample.zip", sample_zip.read(), content_type="application/zip"
        )

        response = client_in_org(admin_acme, acme).post(
            "/api/storage/upload/", {"path": "bundle", "files": uploaded_file}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        rows = StorageFile.objects.filter(org=acme, path__startswith="bundle/")
        assert set(rows.values_list("path", flat=True)) == {
            "bundle/",
            "bundle/sample/",
            "bundle/sample/hello.txt",
            "bundle/sample/sub/",
            "bundle/sample/sub/world.txt",
        }
        assert set(rows.values_list("created_by_id", flat=True)) == {admin_acme.id}


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
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "docs", user=admin_acme)
        manager.upload(acme.id, "docs/a.txt", BytesIO(b"a"), user=admin_acme)

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


class TestRenameAndMove:
    def test_rename_of_unauthored_file_claims_it(
        self, client_in_org, manager, member_only, acme
    ):
        manager.upload(acme.id, "draft.txt", BytesIO(b"x"))

        response = client_in_org(member_only, acme).post(
            "/api/storage/rename/",
            {"from_path": "draft.txt", "to_path": "final.txt"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "final.txt") == member_only.id

    def test_rename_of_authored_file_keeps_author(
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.upload(acme.id, "draft.txt", BytesIO(b"x"), user=admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/rename/",
            {"from_path": "draft.txt", "to_path": "final.txt"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "final.txt") == admin_acme.id

    def test_move_of_folder_claims_only_the_folder_row(
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "archive", user=admin_acme)
        manager.mkdir(acme.id, "docs")
        manager.mkdir(acme.id, "docs/nested")
        manager.upload(acme.id, "docs/a.txt", BytesIO(b"a"))

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/",
            {"from_path": "docs", "to_path": "archive"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "archive/docs/") == member_only.id
        assert _author_id(acme, "archive/docs/nested/") is None
        assert _author_id(acme, "archive/docs/a.txt") is None
        assert _author_id(acme, "archive/") == admin_acme.id

    def test_move_of_unauthored_file_claims_it(self, client_in_org, manager, member_only, acme):
        manager.mkdir(acme.id, "archive")
        manager.upload(acme.id, "report.txt", BytesIO(b"r"))

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/",
            {"from_path": "report.txt", "to_path": "archive"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _author_id(acme, "archive/report.txt") == member_only.id
        assert _author_id(acme, "archive/") is None


class TestCrossOrgTransfers:
    def test_cross_org_copy_authors_destination_rows_by_superadmin(
        self, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        manager.upload(acme.id, "docs/a.txt", BytesIO(b"a"), user=admin_acme)

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

    def test_cross_org_move_of_folder_authors_destination_rows_by_superadmin(
        self, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        manager.mkdir(acme.id, "docs", user=admin_acme)
        manager.upload(acme.id, "docs/a.txt", BytesIO(b"a"), user=admin_acme)

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
        assert set(moved.values_list("path", flat=True)) == {
            "inbox/",
            "inbox/docs/",
            "inbox/docs/a.txt",
        }
        assert set(moved.values_list("created_by_id", flat=True)) == {superadmin.id}
        assert not StorageFile.objects.filter(org=acme).exists()


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
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        graph = Graph.objects.create(name="storage-flow", org=acme)
        manager.upload(acme.id, "tracked.txt", BytesIO(b"t"), user=member_only)

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
        backend.upload(f"org_{acme.id}/docs/a.txt", BytesIO(b"grown"))
        backend.upload(f"org_{acme.id}/docs/b.txt", BytesIO(b"b"))

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
def authored_tree(manager, admin_acme, member_only, acme):
    """`docs/` authored by admin_acme, `docs/a.txt` by member_only, `docs/b.txt` by no one."""
    manager.mkdir(acme.id, "docs", user=admin_acme)
    manager.upload(acme.id, "docs/a.txt", BytesIO(b"a"), user=member_only)
    manager.upload(acme.id, "docs/b.txt", BytesIO(b"b"))


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
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.upload(acme.id, "orphan.txt", BytesIO(b"o"), user=member_only)
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
        self, client_in_org, manager, admin_acme, superadmin, acme, beta
    ):
        manager.upload(beta.id, "beta-only.txt", BytesIO(b"b"), user=superadmin)

        response = client_in_org(admin_acme, acme).get(
            "/api/storage/info/", {"path": "beta-only.txt"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
