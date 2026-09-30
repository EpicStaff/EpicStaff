import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from tables.models import Graph, StorageFile
from tables.services import redis_pubsub
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.reconciler import StorageReconciler
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

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
