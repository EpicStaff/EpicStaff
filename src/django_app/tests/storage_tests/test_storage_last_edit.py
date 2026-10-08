"""Storage writes record the acting user's last edit and storage listings return it."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers, status

from rbac.authorship import record_last_edit
from rbac.models import ResourceLastEdit
from tables.exceptions import StorageUnavailable
from tables.models import Graph, StorageFile
from tables.services import redis_pubsub
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.base import StorageUnreachable
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.reconciler import StorageReconciler
from tables.services.storage_service.upload import file_upload
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, async_chunks
from tests.storage_tests.storage_writes import store_object, stream_upload
from tests.user_summary_helpers import expected_user_summary

pytestmark = pytest.mark.django_db

PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


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


def _row(org, path: str) -> StorageFile:
    return StorageFile.objects.get(org=org, path=path)


def _last_edit(org, path: str) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(StorageFile),
        object_id=_row(org, path).pk,
    ).first()


def _editor_id(org, path: str) -> int | None:
    last_edit = _last_edit(org, path)
    assert last_edit is not None, path
    return last_edit.edited_by_id


def _assert_untouched(org, path: str, editor) -> None:
    last_edit = _last_edit(org, path)
    assert last_edit.edited_by_id == editor.id, path
    assert last_edit.edited_at == PREVIOUS_EDIT_AT, path


def _seed(org, path: str, editor) -> None:
    record_last_edit(_row(org, path), editor, edited_at=PREVIOUS_EDIT_AT)


def _make_commits_fail(monkeypatch, backend) -> None:
    """Make the store refuse every write, so an upload fails after writing its row."""

    def commit_fails(*_args, **_kwargs):
        raise StorageUnreachable("storage went away")

    monkeypatch.setattr(backend, "put_bytes", commit_fails)


@sync_to_async
def _editor_id_async(org, path: str) -> int | None:
    return _editor_id(org, path)


# ---- writes ----


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("stream_backend")
class TestUpload:
    async def test_upload_records_file_and_new_ancestor_folders(self, admin_acme, acme):
        upload_started_at = timezone.now()

        response = await stream_upload(admin_acme, acme, "a/b", "report.txt")

        assert response.status_code == 200, response.text
        for path in ("a/b/report.txt", "a/", "a/b/"):
            last_edit = await sync_to_async(_last_edit)(acme, path)
            assert last_edit.edited_by_id == admin_acme.id
            assert last_edit.edited_at >= upload_started_at

    async def test_upload_into_existing_folder_leaves_its_last_edit(
        self, manager, admin_acme, member_only, acme
    ):
        await sync_to_async(manager.mkdir)(acme.id, "shared", user=member_only)
        await sync_to_async(_seed)(acme, "shared/", member_only)

        response = await stream_upload(admin_acme, acme, "shared", "report.txt")

        assert response.status_code == 200, response.text
        await sync_to_async(_assert_untouched)(acme, "shared/", member_only)
        assert await _editor_id_async(acme, "shared/report.txt") == admin_acme.id

    async def test_reupload_by_another_user_records_that_user(
        self, backend, admin_acme, member_only, acme
    ):
        await sync_to_async(store_object)(
            backend, acme.id, "report.txt", b"first", user=admin_acme
        )
        await sync_to_async(_seed)(acme, "report.txt", admin_acme)

        response = await stream_upload(member_only, acme, "", "report.txt", b"second!")

        assert response.status_code == 200, response.text
        assert await _editor_id_async(acme, "report.txt") == member_only.id

    async def test_failed_overwrite_puts_back_the_previous_last_edit(
        self, backend, monkeypatch, admin_acme, member_only, acme
    ):
        await sync_to_async(store_object)(
            backend, acme.id, "report.txt", b"old", user=admin_acme
        )
        await sync_to_async(_seed)(acme, "report.txt", admin_acme)
        _make_commits_fail(monkeypatch, backend)

        with pytest.raises(StorageUnavailable):
            await file_upload.upload_file(
                acme.id,
                "",
                "report.txt",
                async_chunks(b"new!"),
                4,
                backend=backend,
                user=member_only,
            )

        assert (await StorageFile.objects.aget(org=acme, path="report.txt")).size == 3
        await sync_to_async(_assert_untouched)(acme, "report.txt", admin_acme)

    async def test_failed_overwrite_of_a_never_edited_file_leaves_no_last_edit(
        self, backend, monkeypatch, member_only, acme
    ):
        await sync_to_async(store_object)(backend, acme.id, "report.txt", b"old")
        _make_commits_fail(monkeypatch, backend)

        with pytest.raises(StorageUnavailable):
            await file_upload.upload_file(
                acme.id,
                "",
                "report.txt",
                async_chunks(b"new!"),
                4,
                backend=backend,
                user=member_only,
            )

        assert (await StorageFile.objects.aget(org=acme, path="report.txt")).size == 3
        assert await sync_to_async(_last_edit)(acme, "report.txt") is None

    async def test_archive_upload_records_every_extracted_row(self, admin_acme, acme, sample_zip):
        response = await stream_upload(admin_acme, acme, "", "bundle.zip", sample_zip.read())

        assert response.status_code == 200, response.text
        rows = StorageFile.objects.filter(org=acme).values_list("path", flat=True)
        paths = [path async for path in rows]
        assert len(paths) == 4
        assert {await _editor_id_async(acme, path) for path in paths} == {admin_acme.id}


class TestMkdir:
    def test_mkdir_records_folder_and_new_ancestors(self, client_in_org, member_only, acme):
        response = client_in_org(member_only, acme).post(
            "/api/storage/mkdir/", {"path": "projects/alpha"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert _editor_id(acme, "projects/alpha/") == member_only.id
        assert _editor_id(acme, "projects/") == member_only.id

    def test_mkdir_under_existing_folder_leaves_its_last_edit(
        self, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "projects", user=admin_acme)
        _seed(acme, "projects/", admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/mkdir/", {"path": "projects/alpha"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        _assert_untouched(acme, "projects/", admin_acme)


class TestCopy:
    def test_copy_records_every_new_row_and_leaves_existing_rows(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "docs", user=admin_acme)
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)
        manager.mkdir(acme.id, "backup", user=admin_acme)
        for path in ("docs/", "docs/a.txt", "backup/"):
            _seed(acme, path, admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/copy/", {"from_path": "docs", "to_path": "backup"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _editor_id(acme, "backup/docs/") == member_only.id
        assert _editor_id(acme, "backup/docs/a.txt") == member_only.id
        for path in ("docs/", "docs/a.txt", "backup/"):
            _assert_untouched(acme, path, admin_acme)


class TestRenameAndMove:
    def test_rename_records_the_renamed_file(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        store_object(backend, acme.id, "draft.txt", b"x", user=admin_acme)
        _seed(acme, "draft.txt", admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/rename/", {"from_path": "draft.txt", "to_path": "final.txt"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _editor_id(acme, "final.txt") == member_only.id

    def test_move_of_folder_records_only_the_folder_row(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "archive", user=admin_acme)
        manager.mkdir(acme.id, "docs/nested", user=admin_acme)
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)
        for path in ("archive/", "docs/", "docs/nested/", "docs/a.txt"):
            _seed(acme, path, admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/", {"from_path": "docs", "to_path": "archive"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _editor_id(acme, "archive/docs/") == member_only.id
        for path in ("archive/", "archive/docs/nested/", "archive/docs/a.txt"):
            _assert_untouched(acme, path, admin_acme)

    def test_move_of_file_records_only_the_file_row(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        manager.mkdir(acme.id, "archive", user=admin_acme)
        store_object(backend, acme.id, "report.txt", b"r", user=admin_acme)
        for path in ("archive/", "report.txt"):
            _seed(acme, path, admin_acme)

        response = client_in_org(member_only, acme).post(
            "/api/storage/move/", {"from_path": "report.txt", "to_path": "archive"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _editor_id(acme, "archive/report.txt") == member_only.id
        _assert_untouched(acme, "archive/", admin_acme)


class TestCrossOrgTransfers:
    def test_cross_org_copy_records_destination_rows(
        self, backend, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        store_object(backend, acme.id, "docs/a.txt", b"a", user=admin_acme)
        _seed(acme, "docs/a.txt", admin_acme)

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
        assert _editor_id(beta, "inbox/a.txt") == superadmin.id
        assert _editor_id(beta, "inbox/") == superadmin.id
        _assert_untouched(acme, "docs/a.txt", admin_acme)

    def test_cross_org_move_of_folder_records_every_destination_row(
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
        paths = StorageFile.objects.filter(org=beta).values_list("path", flat=True)
        assert set(paths) == {"inbox/", "inbox/docs/", "inbox/docs/a.txt"}
        assert {_editor_id(beta, path) for path in paths} == {superadmin.id}

    def test_cross_org_move_of_file_records_destination_file(
        self, backend, client_in_org, manager, superadmin, admin_acme, acme, beta
    ):
        store_object(backend, acme.id, "report.txt", b"r", user=admin_acme)

        response = client_in_org(superadmin, acme).post(
            "/api/storage/move/",
            {
                "from_path": "report.txt",
                "to_path": "inbox",
                "source_org_id": acme.id,
                "destination_org_id": beta.id,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _editor_id(beta, "inbox/report.txt") == superadmin.id
        assert _editor_id(beta, "inbox/") == superadmin.id


class TestAddToGraph:
    def test_add_to_graph_records_a_newly_tracked_row(self, client_in_org, admin_acme, acme):
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
        assert _editor_id(acme, "untracked.txt") == admin_acme.id

    def test_add_to_graph_leaves_tracked_row(
        self, backend, client_in_org, manager, admin_acme, member_only, acme
    ):
        graph = Graph.objects.create(name="storage-flow", org=acme)
        store_object(backend, acme.id, "tracked.txt", b"t", user=member_only)
        _seed(acme, "tracked.txt", member_only)

        response = client_in_org(admin_acme, acme).post(
            "/api/storage/add-to-graph/",
            {"paths": ["tracked.txt"], "graph_ids": [graph.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        _assert_untouched(acme, "tracked.txt", member_only)


class TestSystemWritesRecordNothing:
    def test_redis_storage_mutation_records_nothing(self, monkeypatch, acme):
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

        assert StorageFile.objects.filter(org=acme).count() == 2
        assert not ResourceLastEdit.objects.exists()

    def test_redis_overwrite_leaves_existing_last_edit(
        self, backend, monkeypatch, manager, member_only, acme
    ):
        store_object(backend, acme.id, "out/result.txt", b"r", user=member_only)
        _seed(acme, "out/result.txt", member_only)
        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: MagicMock()
        )
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        message = {
            "data": json.dumps(
                {
                    "execution_id": "exec-2",
                    "org_prefix": f"org_{acme.id}",
                    "mutations": [{"op": "write", "path": f"org_{acme.id}/out/result.txt"}],
                }
            )
        }

        redis_pubsub.RedisPubSub().storage_mutations_handler(message)

        _assert_untouched(acme, "out/result.txt", member_only)

    def test_reconciler_records_nothing(self, backend, acme):
        backend.put_bytes(f"org_{acme.id}/docs/b.txt", b"b")

        StorageReconciler(backend).reconcile_tree(acme.id)

        assert StorageFile.objects.filter(org=acme).count() == 2
        assert not ResourceLastEdit.objects.exists()

    def test_manager_calls_without_user_record_nothing(self, backend, manager, acme):
        manager.mkdir(acme.id, "docs")
        store_object(backend, acme.id, "docs/a.txt", b"a")
        manager.copy(acme.id, "docs", "copy")
        manager.rename(acme.id, "docs/a.txt", "docs/b.txt")

        assert StorageFile.objects.filter(org=acme).exists()
        assert not ResourceLastEdit.objects.exists()


# ---- listing output ----


@pytest.fixture
def edited_tree(backend, manager, admin_acme, member_only, acme):
    """Folder `docs/` edited by admin_acme, `docs/a.txt` by member_only, `docs/b.txt` by no one."""
    manager.mkdir(acme.id, "docs", user=admin_acme)
    store_object(backend, acme.id, "docs/a.txt", b"a", user=member_only)
    store_object(backend, acme.id, "docs/b.txt", b"b")
    _seed(acme, "docs/", admin_acme)
    _seed(acme, "docs/a.txt", member_only)


EXPECTED_EDITED_AT = serializers.DateTimeField().to_representation(PREVIOUS_EDIT_AT)


def _assert_last_edit_fields(entry: dict, editor) -> None:
    if editor is None:
        assert entry["last_edited_by"] is None
        assert entry["last_edited_at"] is None
    else:
        assert entry["last_edited_by"] == expected_user_summary(editor)
        assert entry["last_edited_at"] == EXPECTED_EDITED_AT


class TestListingOutput:
    def test_list_returns_last_edit_of_each_entry(
        self, client_in_org, edited_tree, admin_acme, member_only, acme
    ):
        client = client_in_org(admin_acme, acme)

        root = client.get("/api/storage/list/", {"path": ""})
        folder = client.get("/api/storage/list/", {"path": "docs"})

        assert root.status_code == status.HTTP_200_OK, root.data
        _assert_last_edit_fields(root.data["items"][0], admin_acme)
        items = {item["name"]: item for item in folder.data["items"]}
        _assert_last_edit_fields(items["a.txt"], member_only)
        _assert_last_edit_fields(items["b.txt"], None)

    def test_info_returns_last_edit_of_file_and_folder(
        self, client_in_org, edited_tree, admin_acme, member_only, acme
    ):
        client = client_in_org(admin_acme, acme)

        file_info = client.get("/api/storage/info/", {"path": "docs/a.txt"})
        folder_info = client.get("/api/storage/info/", {"path": "docs"})

        assert file_info.status_code == status.HTTP_200_OK, file_info.data
        _assert_last_edit_fields(file_info.data, member_only)
        _assert_last_edit_fields(folder_info.data, admin_acme)

    def test_tree_returns_last_edit_of_each_node(
        self, client_in_org, edited_tree, admin_acme, member_only, acme
    ):
        response = client_in_org(admin_acme, acme).get("/api/storage/tree/", {"path": ""})

        assert response.status_code == status.HTTP_200_OK, response.data
        root = response.data["tree"]
        _assert_last_edit_fields(root, None)
        docs = root["children"][0]
        _assert_last_edit_fields(docs, admin_acme)
        children = {child["name"]: child for child in docs["children"]}
        _assert_last_edit_fields(children["a.txt"], member_only)
        _assert_last_edit_fields(children["b.txt"], None)

    def test_search_returns_last_edit_of_each_result(
        self, client_in_org, edited_tree, admin_acme, member_only, acme
    ):
        response = client_in_org(admin_acme, acme).get("/api/storage/search/", {"q": ".txt"})

        assert response.status_code == status.HTTP_200_OK, response.data
        results = {result["name"]: result for result in response.data["results"]}
        _assert_last_edit_fields(results["a.txt"], member_only)
        _assert_last_edit_fields(results["b.txt"], None)

    def test_files_by_ids_returns_editor_with_absolute_avatar(
        self, client_in_org, edited_tree, admin_acme, member_only, acme
    ):
        member_only.display_name = "Member Only"
        member_only.avatar.name = f"avatars/{member_only.id}/face.png"
        member_only.save(update_fields=["display_name", "avatar"])
        file_row = _row(acme, "docs/a.txt")

        response = client_in_org(admin_acme, acme).get(
            "/api/storage/files/", {"ids": str(file_row.id)}
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data[0]["last_edited_by"] == {
            "id": member_only.id,
            "display_name": "Member Only",
            "avatar_url": f"http://testserver/media/avatars/{member_only.id}/face.png",
        }

    def test_listing_never_shows_another_orgs_entries(
        self, backend, client_in_org, manager, admin_acme, superadmin, acme, beta
    ):
        store_object(backend, beta.id, "secret.txt", b"s", user=superadmin)

        response = client_in_org(admin_acme, acme).get("/api/storage/list/", {"path": ""})

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["items"] == []


def _count_listing_queries(client, url: str, params: dict) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(url, params)
    assert response.status_code == status.HTTP_200_OK, response.data
    return len(context.captured_queries)


@pytest.mark.parametrize(
    ("url", "params"),
    [
        ("/api/storage/list/", {"path": "docs"}),
        ("/api/storage/tree/", {"path": "docs"}),
        ("/api/storage/search/", {"q": ".txt"}),
    ],
    ids=["list", "tree", "search"],
)
def test_listing_query_count_does_not_grow_with_entries(
    backend, client_in_org, manager, admin_acme, acme, url, params
):
    client = client_in_org(admin_acme, acme)
    manager.mkdir(acme.id, "docs", user=admin_acme)
    store_object(backend, acme.id, "docs/first.txt", b"1", user=admin_acme)
    few_entries = _count_listing_queries(client, url, params)
    for index in range(4):
        store_object(backend, acme.id, f"docs/more-{index}.txt", b"n", user=admin_acme)

    assert _count_listing_queries(client, url, params) == few_entries


def _count_user_queries(client, url: str, params: dict) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(url, params)
    assert response.status_code == status.HTTP_200_OK, response.data
    return sum('FROM "rbac_user"' in query["sql"] for query in context.captured_queries)


@pytest.mark.parametrize(
    ("url", "params"),
    [
        ("/api/storage/list/", {"path": "docs"}),
        ("/api/storage/tree/", {"path": ""}),
        ("/api/storage/search/", {"q": ".txt"}),
    ],
    ids=["list", "tree", "search"],
)
def test_listing_resolves_every_editor_in_one_user_query(
    backend, client_in_org, manager, admin_acme, member_only, acme, url, params
):
    client = client_in_org(admin_acme, acme)
    manager.mkdir(acme.id, "docs", user=admin_acme)
    manager.mkdir(acme.id, "docs/nested", user=member_only)
    store_object(backend, acme.id, "docs/first.txt", b"1", user=admin_acme)
    store_object(backend, acme.id, "docs/second.txt", b"2", user=member_only)
    store_object(backend, acme.id, "docs/nested/third.txt", b"3", user=member_only)

    assert _count_user_queries(client, url, params) == 1


def test_listing_ignores_last_edit_of_another_model_with_the_same_id(
    backend, client_in_org, manager, admin_acme, superadmin, acme, beta
):
    store_object(backend, acme.id, "report.txt", b"r")
    file_row = _row(acme, "report.txt")
    foreign_graph = Graph.objects.create(pk=file_row.pk, name="beta-flow", org=beta)
    record_last_edit(foreign_graph, superadmin, edited_at=PREVIOUS_EDIT_AT)
    client = client_in_org(admin_acme, acme)

    listed = client.get("/api/storage/list/", {"path": ""})
    tree = client.get("/api/storage/tree/", {"path": ""})
    info = client.get("/api/storage/info/", {"path": "report.txt"})
    search = client.get("/api/storage/search/", {"q": "report"})

    assert listed.status_code == status.HTTP_200_OK, listed.data
    assert len(listed.data["items"]) == 1
    _assert_last_edit_fields(listed.data["items"][0], None)
    assert len(tree.data["tree"]["children"]) == 1
    _assert_last_edit_fields(tree.data["tree"]["children"][0], None)
    _assert_last_edit_fields(info.data, None)
    assert search.data["total"] == 1
    assert len(search.data["results"]) == 1
    _assert_last_edit_fields(search.data["results"][0], None)
