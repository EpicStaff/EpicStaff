from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse
from loguru import logger
from rest_framework import status

from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models.api_key import ApiKey
from tables.models import DocumentContent, DocumentMetadata, SourceCollection, StorageFile
from tables.views.knowledge_views.document_management_views import _audit_actor
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

_VIEW_STORAGE_MANAGER = "tables.views.knowledge_views.document_management_views.get_storage_manager"


class _BackendWithDownloadHook(InMemoryStorageBackend):
    """In-memory backend that runs a callback on every download."""

    def __init__(self, on_download):
        super().__init__(organization_prefix="")
        self._on_download = on_download

    def download(self, path: str) -> bytes:
        self._on_download()
        return super().download(path)


@pytest.fixture
def storage_manager():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch(_VIEW_STORAGE_MANAGER, return_value=manager):
        yield manager


def _store(storage_manager, org, path: str, content: bytes) -> StorageFile:
    seed_file(storage_manager._backend, org.id, path, content)
    return StorageFile.objects.get(org=org, path=path)


def _url(collection_id) -> str:
    return reverse("document-import-from-storage", args=[collection_id])


def _post(client, collection, storage_file_ids):
    return client.post(
        _url(collection.collection_id), {"storage_file_ids": storage_file_ids}, format="json"
    )


def _document_count(collection) -> int:
    return DocumentMetadata.objects.filter(source_collection=collection).count()


class TestAuditActor:
    def test_jwt_user_is_named_by_user_id(self):
        request = SimpleNamespace(auth=None, user=SimpleNamespace(pk=5))

        assert _audit_actor(request) == "user:5"

    def test_user_api_key_names_the_owner_and_the_key(self):
        api_key = ApiKey(id=12, key_type=ApiKey.KeyType.USER)
        request = SimpleNamespace(auth=api_key, user=SimpleNamespace(pk=5))

        assert _audit_actor(request) == "user:5 via api_key:12"

    def test_system_api_key_has_no_user_and_is_named_by_the_key(self):
        api_key = ApiKey(id=12, key_type=ApiKey.KeyType.SYSTEM)
        request = SimpleNamespace(auth=api_key, user=SystemServicePrincipal())

        assert _audit_actor(request) == "system api_key:12"


@pytest.fixture
def audit_log():
    """Messages logged through loguru during the test (caplog does not see loguru)."""
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]), level="INFO"
    )
    yield messages
    logger.remove(handler_id)


class TestImportFromStorage:
    def test_audit_line_names_the_requesting_user_and_the_files(
        self, auth_client, regular_user, storage_manager, default_org, empty_collection, audit_log
    ):
        stored = _store(storage_manager, default_org, "reports/q3.txt", b"quarter three")

        response = _post(auth_client, empty_collection, [stored.id])

        assert response.status_code == status.HTTP_201_CREATED, response.data
        [line] = [message for message in audit_log if message.startswith("Storage import:")]
        assert f"user:{regular_user.pk} in org {default_org.id}" in line
        assert f"collection {empty_collection.collection_id}" in line
        assert f"({stored.id}, 'reports/q3.txt')" in line
        assert "quarter three" not in line

    def test_imports_files_with_their_bytes(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        stored = _store(storage_manager, default_org, "reports/q3.txt", b"quarter three")

        response = _post(auth_client, empty_collection, [stored.id])

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["skipped"] == []
        assert response.data["message"] == "Successfully imported 1 file(s)"
        [document_data] = response.data["documents"]
        assert set(document_data) == {
            "document_id",
            "file_name",
            "file_type",
            "file_size",
            "source_collection",
        }
        assert document_data["file_name"] == "q3.txt"
        assert document_data["file_type"] == "txt"
        assert document_data["file_size"] == len(b"quarter three")
        assert document_data["source_collection"] == empty_collection.collection_id

        document = DocumentMetadata.objects.get(document_id=document_data["document_id"])
        assert bytes(document.document_content.content) == b"quarter three"

        empty_collection.refresh_from_db()
        assert empty_collection.status == SourceCollection.SourceCollectionStatus.COMPLETED

    @override_settings(MAX_UPLOAD_FILE_SIZE=10)
    def test_201_body_serializes_skipped_files(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        _store(storage_manager, default_org, "docs/a.txt", b"a")
        _store(storage_manager, default_org, "docs/nested/deeper/b.md", b"bb")
        sheet = _store(storage_manager, default_org, "docs/sheet.xlsx", b"xl")
        big = _store(storage_manager, default_org, "docs/big.txt", b"x" * 11)
        seen = _store(storage_manager, default_org, "docs/nested/seen.txt", b"seen")
        system_file = _store(storage_manager, default_org, "docs/system.txt", b"sys")
        StorageFile.objects.filter(id=system_file.id).update(is_system=True)
        DocumentMetadata.objects.create(
            source_collection=empty_collection,
            document_content=DocumentContent.objects.create(content=b"seen"),
            file_name="seen.txt",
            file_type="txt",
            file_size=4,
        )
        folder = StorageFile.objects.get(org=default_org, path="docs/")

        response = _post(auth_client, empty_collection, [folder.id])

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert sorted(item["file_name"] for item in response.data["documents"]) == [
            "a.txt",
            "b.md",
        ]
        assert sorted(response.data["skipped"], key=lambda item: item["path"]) == [
            {"storage_file_id": big.id, "path": "docs/big.txt", "reason": "too_large"},
            {"storage_file_id": seen.id, "path": "docs/nested/seen.txt", "reason": "duplicate"},
            {
                "storage_file_id": sheet.id,
                "path": "docs/sheet.xlsx",
                "reason": "unsupported_type",
            },
        ]
        assert response.data["message"] == "Successfully imported 2 file(s), skipped 3"
        assert not DocumentMetadata.objects.filter(file_name="system.txt").exists()

    def test_everything_skipped_is_400_with_skipped(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        sheet = _store(storage_manager, default_org, "sheet.xlsx", b"xl")

        response = _post(auth_client, empty_collection, [sheet.id])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {
            "error": "None of the selected storage files can be imported",
            "skipped": [
                {"storage_file_id": sheet.id, "path": "sheet.xlsx", "reason": "unsupported_type"}
            ],
        }
        assert _document_count(empty_collection) == 0

    @override_settings(MAX_ARCHIVE_ENTRIES=2)
    def test_over_the_count_limit_is_400(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        ids = [
            _store(storage_manager, default_org, f"file{index}.txt", b"x").id
            for index in range(3)
        ]

        response = _post(auth_client, empty_collection, ids)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {"error"}
        assert "limit is 2" in response.data["error"]
        assert _document_count(empty_collection) == 0

    @override_settings(MAX_UPLOAD_TOTAL_SIZE=10)
    def test_over_the_total_size_limit_is_400(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        ids = [
            _store(storage_manager, default_org, f"file{index}.txt", b"x" * 6).id
            for index in range(2)
        ]

        response = _post(auth_client, empty_collection, ids)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Total import size" in response.data["error"]

    def test_duplicate_ids_are_imported_once(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        stored = _store(storage_manager, default_org, "a.txt", b"a")

        response = _post(auth_client, empty_collection, [stored.id, stored.id])

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert len(response.data["documents"]) == 1
        assert _document_count(empty_collection) == 1

    @pytest.mark.parametrize(
        "storage_file_ids",
        [[], [0], [-3], ["abc"], [1.5], "1,2", None],
        ids=["empty", "zero", "negative", "string", "float", "not-a-list", "null"],
    )
    def test_invalid_storage_file_ids_are_400(
        self, auth_client, storage_manager, empty_collection, storage_file_ids
    ):
        response = _post(auth_client, empty_collection, storage_file_ids)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _document_count(empty_collection) == 0

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_more_ids_than_the_selection_cap_is_400(
        self, auth_client, storage_manager, empty_collection
    ):
        # The cap is max_storage_selection(): 2 per allowed file, so 2 here.
        response = _post(auth_client, empty_collection, [1, 2, 3])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "storage_file_ids" in response.data["message"]

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_ids_at_the_selection_cap_pass_the_serializer(
        self, auth_client, storage_manager, empty_collection
    ):
        # Unknown ids get past validation and fail the org-scoped lookup instead.
        response = _post(auth_client, empty_collection, [999_998, 999_999])

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_storage_file_ids_is_400(self, auth_client, storage_manager, empty_collection):
        response = auth_client.post(_url(empty_collection.collection_id), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_numeric_collection_id_is_400(self, auth_client, storage_manager):
        response = auth_client.post(_url("abc"), {"storage_file_ids": [1]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_storage_id_is_404(
        self, auth_client, storage_manager, default_org, empty_collection
    ):
        stored = _store(storage_manager, default_org, "a.txt", b"a")

        response = _post(auth_client, empty_collection, [stored.id, stored.id + 10_000])

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert _document_count(empty_collection) == 0

    def test_unauthenticated_is_401(self, api_client, default_org, empty_collection):
        api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))

        response = _post(api_client, empty_collection, [1])

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # delete() depends on settings.SOFT_DELETE, so each mode is exercised explicitly.
    @pytest.mark.parametrize("delete_mode", ["soft", "hard"])
    def test_collection_deleted_mid_request_is_404(
        self, auth_client, default_org, empty_collection, delete_mode
    ):
        def delete_collection_before_write():
            if SourceCollection.objects.filter(
                collection_id=empty_collection.collection_id
            ).exists():
                if delete_mode == "soft":
                    empty_collection.soft_delete()
                else:
                    empty_collection.hard_delete()

        manager = StorageManager(_BackendWithDownloadHook(delete_collection_before_write))
        stored = _store(manager, default_org, "late.txt", b"late")

        with patch(_VIEW_STORAGE_MANAGER, return_value=manager):
            response = _post(auth_client, empty_collection, [stored.id])

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {"status_code": 404, "code": "not_found", "message": "Not found."}
        assert not DocumentMetadata.objects.filter(file_name="late.txt").exists()
