from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from loguru import logger

from tables.exceptions import (
    CollectionNotFoundException,
    NothingToImportException,
    StorageFilesNotFoundException,
    StorageImportLimitExceededException,
)
from tables.models import DocumentContent, DocumentMetadata, SourceCollection, StorageFile
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.knowledge_services.storage_document_import_service import (
    SkippedStorageFile,
    SkipReason,
    StorageDocumentImportService,
    _shorten_path_for_log,
)
from tables.services.storage_service.manager import StorageManager
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db

_ACTOR = "user:42"


@pytest.fixture
def audit_log():
    """Messages of the storage-import audit lines logged during the test.

    loguru bypasses stdlib logging, so pytest's caplog does not see it; a
    temporary sink is added instead.
    """
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]), level="INFO"
    )
    yield messages
    logger.remove(handler_id)


def _audit_lines(messages: list[str]) -> list[str]:
    return [message for message in messages if message.startswith("Storage import:")]


class _BackendWithDownloadHook(InMemoryStorageBackend):
    """In-memory backend that runs a callback on every download, to change
    state between the pre-download checks and the write."""

    def __init__(self, on_download):
        super().__init__(organization_prefix="")
        self._on_download = on_download

    def download(self, path: str) -> bytes:
        self._on_download()
        return super().download(path)


class _CountingSizeLookups(InMemoryStorageBackend):
    """In-memory backend that records the paths whose size was looked up."""

    def __init__(self):
        super().__init__(organization_prefix="")
        self.info_paths: list[str] = []

    def info(self, path: str):
        self.info_paths.append(path)
        return super().info(path)


def _delete_collection(collection, delete_mode: str) -> None:
    """Delete explicitly in one mode: `delete()` depends on settings.SOFT_DELETE."""
    if delete_mode == "soft":
        collection.soft_delete()
    else:
        collection.hard_delete()


@pytest.fixture
def storage_manager():
    yield StorageManager(InMemoryStorageBackend(organization_prefix=""))


@pytest.fixture
def import_service(storage_manager):
    yield StorageDocumentImportService(storage_manager)


@pytest.fixture
def collection(acme):
    yield SourceCollection.objects.create(collection_name="target", org=acme)


def _store(storage_manager, org, path: str, content: bytes) -> StorageFile:
    storage_manager.upload(org.id, path, BytesIO(content))
    return StorageFile.objects.get(org=org, path=path)


def _store_without_size(storage_manager, org, path: str, content: bytes) -> StorageFile:
    """A stored file whose index row has no size, as StorageFileSync.on_copy leaves it."""
    row = _store(storage_manager, org, path, content)
    StorageFile.objects.filter(id=row.id).update(size=None)
    row.refresh_from_db()
    return row


def _folder(org, path: str) -> StorageFile:
    return StorageFile.objects.get(org=org, path=path, item_type="folder")


def _index_only(org, path: str, size: int | None) -> StorageFile:
    """A storage index row whose object was never written to the backend."""
    return StorageFile.objects.create(
        org=org, path=path, name=path.rsplit("/", 1)[-1], item_type="file", size=size
    )


def _existing_document(collection, file_name: str, content: bytes) -> DocumentMetadata:
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=content),
        file_name=file_name,
        file_type=file_name.rsplit(".", 1)[-1],
        file_size=len(content),
    )


def _document_names(collection) -> list[str]:
    return sorted(
        DocumentMetadata.objects.filter(source_collection=collection).values_list(
            "file_name", flat=True
        )
    )


class TestImportFiles:
    def test_creates_documents_with_storage_bytes(
        self, import_service, storage_manager, acme, collection
    ):
        notes = _store(storage_manager, acme, "notes.txt", b"plain notes")
        readme = _store(storage_manager, acme, "docs/readme.md", b"# Readme")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [notes.id, readme.id]
        )

        assert result.skipped == []
        documents = {document.file_name: document for document in result.documents}
        assert set(documents) == {"notes.txt", "readme.md"}
        assert documents["readme.md"].file_type == "md"
        assert documents["readme.md"].file_size == len(b"# Readme")
        assert documents["readme.md"].source_collection_id == collection.collection_id
        assert bytes(documents["notes.txt"].document_content.content) == b"plain notes"

    def test_expands_folders_to_nested_files_only(
        self, import_service, storage_manager, acme, collection
    ):
        _store(storage_manager, acme, "docs/a.txt", b"a")
        _store(storage_manager, acme, "docs/deep/b.md", b"bb")
        _store(storage_manager, acme, "docs-archive/c.txt", b"ccc")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [_folder(acme, "docs/").id]
        )

        assert sorted(document.file_name for document in result.documents) == ["a.txt", "b.md"]

    def test_folder_expansion_stays_in_the_callers_org(
        self, import_service, storage_manager, acme, beta, collection
    ):
        _store(storage_manager, acme, "docs/mine.txt", b"mine")
        _store(storage_manager, beta, "docs/x.txt", b"theirs")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [_folder(acme, "docs/").id]
        )

        assert [document.file_name for document in result.documents] == ["mine.txt"]
        assert _document_names(collection) == ["mine.txt"]

    def test_folder_and_a_file_inside_it_import_the_file_once(
        self, import_service, storage_manager, acme, collection
    ):
        inner = _store(storage_manager, acme, "docs/a.txt", b"a")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [_folder(acme, "docs/").id, inner.id]
        )

        assert [document.file_name for document in result.documents] == ["a.txt"]
        assert _document_names(collection) == ["a.txt"]

    def test_folder_expansion_leaves_out_system_files(
        self, import_service, storage_manager, acme, collection
    ):
        _store(storage_manager, acme, "out/user.txt", b"mine")
        system_file = _store(storage_manager, acme, "out/system.txt", b"platform")
        StorageFile.objects.filter(id=system_file.id).update(is_system=True)

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [_folder(acme, "out/").id]
        )

        assert [document.file_name for document in result.documents] == ["user.txt"]
        assert result.skipped == []

    @override_settings(MAX_UPLOAD_FILE_SIZE=10)
    def test_skips_unsupported_too_large_and_duplicate(
        self, import_service, storage_manager, acme, collection
    ):
        good = _store(storage_manager, acme, "good.txt", b"fine")
        sheet = _store(storage_manager, acme, "sheet.xlsx", b"xl")
        big = _store(storage_manager, acme, "big.txt", b"x" * 11)
        already = _store(storage_manager, acme, "already.txt", b"seen")
        same_name_other_size = _store(storage_manager, acme, "resized.txt", b"new size")
        _existing_document(collection, "already.txt", b"seen")
        _existing_document(collection, "resized.txt", b"old")

        result = import_service.import_files(
            _ACTOR, acme.id,
            collection.collection_id,
            [good.id, sheet.id, big.id, already.id, same_name_other_size.id],
        )

        assert sorted(document.file_name for document in result.documents) == [
            "good.txt",
            "resized.txt",
        ]
        assert set(result.skipped) == {
            SkippedStorageFile(sheet.id, "sheet.xlsx", SkipReason.UNSUPPORTED_TYPE),
            SkippedStorageFile(big.id, "big.txt", SkipReason.TOO_LARGE),
            SkippedStorageFile(already.id, "already.txt", SkipReason.DUPLICATE),
        }

    def test_same_file_in_two_folders_is_imported_once(
        self, import_service, storage_manager, acme, collection
    ):
        first = _store(storage_manager, acme, "a/report.txt", b"same")
        second = _store(storage_manager, acme, "b/report.txt", b"same")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [first.id, second.id]
        )

        assert [document.file_name for document in result.documents] == ["report.txt"]
        assert result.skipped == [
            SkippedStorageFile(second.id, "b/report.txt", SkipReason.DUPLICATE)
        ]

    def test_everything_skipped_raises_with_the_skips(
        self, import_service, storage_manager, acme, collection
    ):
        sheet = _store(storage_manager, acme, "sheet.xlsx", b"xl")

        with pytest.raises(NothingToImportException) as raised:
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [sheet.id])

        assert raised.value.skipped == [
            SkippedStorageFile(sheet.id, "sheet.xlsx", SkipReason.UNSUPPORTED_TYPE)
        ]
        assert _document_names(collection) == []

    def test_explicit_system_file_is_not_found(
        self, import_service, storage_manager, acme, collection
    ):
        system_file = _store(storage_manager, acme, "system.txt", b"platform")
        StorageFile.objects.filter(id=system_file.id).update(is_system=True)

        with pytest.raises(StorageFilesNotFoundException):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [system_file.id])

    def test_other_org_file_is_not_found_and_nothing_is_created(
        self, import_service, storage_manager, acme, beta, collection
    ):
        mine = _store(storage_manager, acme, "mine.txt", b"mine")
        theirs = _store(storage_manager, beta, "theirs.txt", b"theirs")

        with pytest.raises(StorageFilesNotFoundException):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [mine.id, theirs.id]
            )

        assert _document_names(collection) == []

    def test_other_org_folder_is_not_found(
        self, import_service, storage_manager, acme, beta, collection
    ):
        _store(storage_manager, beta, "shared/theirs.txt", b"theirs")

        with pytest.raises(StorageFilesNotFoundException):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [_folder(beta, "shared/").id]
            )

    def test_missing_object_is_not_found(self, import_service, acme, collection):
        orphan = _index_only(acme, "orphan.txt", size=4)

        with pytest.raises(StorageFilesNotFoundException):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [orphan.id])

        assert _document_names(collection) == []


class TestUnknownIndexSize:
    """Rows written by StorageFileSync.on_copy carry size=NULL; the real size
    must be read from the object store before any screening."""

    @override_settings(MAX_UPLOAD_FILE_SIZE=10)
    def test_null_size_row_that_is_too_large_is_skipped(
        self, import_service, storage_manager, acme, collection
    ):
        good = _store(storage_manager, acme, "good.txt", b"fine")
        copied_big = _store_without_size(storage_manager, acme, "copied/big.txt", b"x" * 11)

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [good.id, copied_big.id]
        )

        assert [document.file_name for document in result.documents] == ["good.txt"]
        assert result.skipped == [
            SkippedStorageFile(copied_big.id, "copied/big.txt", SkipReason.TOO_LARGE)
        ]

    def test_null_size_row_that_is_a_duplicate_is_skipped(
        self, import_service, storage_manager, acme, collection
    ):
        copied = _store_without_size(storage_manager, acme, "copied/seen.txt", b"seen")
        _existing_document(collection, "seen.txt", b"seen")

        with pytest.raises(NothingToImportException) as raised:
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [copied.id])

        assert raised.value.skipped == [
            SkippedStorageFile(copied.id, "copied/seen.txt", SkipReason.DUPLICATE)
        ]
        assert _document_names(collection) == ["seen.txt"]

    @override_settings(MAX_UPLOAD_TOTAL_SIZE=10)
    def test_null_size_rows_count_their_real_size_toward_the_total(
        self, import_service, storage_manager, acme, collection
    ):
        rows = [
            _store_without_size(storage_manager, acme, f"copied/file{index}.txt", b"x" * 6)
            for index in range(2)
        ]

        with pytest.raises(StorageImportLimitExceededException, match="Total import size"):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [row.id for row in rows]
            )

    def test_unsupported_type_is_skipped_without_a_size_lookup(self, acme, collection):
        backend = _CountingSizeLookups()
        storage_manager = StorageManager(backend)
        sheet = _store_without_size(storage_manager, acme, "copied/sheet.xlsx", b"xl")
        good = _store_without_size(storage_manager, acme, "copied/good.txt", b"fine")

        result = StorageDocumentImportService(storage_manager).import_files(
            _ACTOR, acme.id, collection.collection_id, [sheet.id, good.id]
        )

        assert backend.info_paths == [f"org_{acme.id}/copied/good.txt"]
        assert [document.file_name for document in result.documents] == ["good.txt"]
        assert result.skipped == [
            SkippedStorageFile(sheet.id, "copied/sheet.xlsx", SkipReason.UNSUPPORTED_TYPE)
        ]

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_count_limit_is_checked_before_any_size_lookup(self, acme, collection):
        backend = _CountingSizeLookups()
        storage_manager = StorageManager(backend)
        rows = [
            _store_without_size(storage_manager, acme, f"copied/file{index}.txt", b"x")
            for index in range(2)
        ]

        with pytest.raises(StorageImportLimitExceededException, match="limit is 1"):
            StorageDocumentImportService(storage_manager).import_files(
                _ACTOR, acme.id, collection.collection_id, [row.id for row in rows]
            )

        assert backend.info_paths == []

    def test_null_size_row_without_an_object_is_not_found(
        self, import_service, acme, collection
    ):
        orphan = _index_only(acme, "copied/orphan.txt", size=None)

        with pytest.raises(StorageFilesNotFoundException):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [orphan.id])


class TestLimits:
    """Rows are indexed but have no bytes in the backend: if the service
    downloaded before checking limits, it would fail with not-found instead."""

    @override_settings(MAX_ARCHIVE_ENTRIES=2)
    def test_count_limit_is_checked_before_download(self, import_service, acme, collection):
        rows = [_index_only(acme, f"file{index}.txt", size=1) for index in range(3)]

        with pytest.raises(StorageImportLimitExceededException, match="limit is 2"):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [row.id for row in rows]
            )

    @override_settings(MAX_UPLOAD_TOTAL_SIZE=10)
    def test_total_size_limit_is_checked_before_download(self, import_service, acme, collection):
        rows = [_index_only(acme, f"file{index}.txt", size=6) for index in range(2)]

        with pytest.raises(StorageImportLimitExceededException, match="Total import size"):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [row.id for row in rows]
            )

    @override_settings(MAX_ARCHIVE_ENTRIES=1, MAX_UPLOAD_FILE_SIZE=10)
    def test_supported_files_count_toward_the_limit_even_if_too_large(
        self, import_service, storage_manager, acme, collection
    ):
        good = _store(storage_manager, acme, "good.txt", b"fine")
        big = _store(storage_manager, acme, "big.txt", b"x" * 11)

        with pytest.raises(StorageImportLimitExceededException, match="limit is 1"):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [good.id, big.id]
            )

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_unsupported_files_do_not_count_toward_the_limit(
        self, import_service, storage_manager, acme, collection
    ):
        good = _store(storage_manager, acme, "good.txt", b"fine")
        sheet = _store(storage_manager, acme, "sheet.xlsx", b"xl")

        result = import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [good.id, sheet.id]
        )

        assert [document.file_name for document in result.documents] == ["good.txt"]

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_folder_expansion_is_capped_at_the_query(self, import_service, acme, collection):
        # Cap is 2 candidates per importable file: 3 unsupported rows exceed it
        # even though none of them would be imported.
        for index in range(3):
            _index_only(acme, f"big-folder/sheet{index}.xlsx", size=1)
        StorageFile.objects.create(
            org=acme, path="big-folder/", name="big-folder", item_type="folder"
        )

        with pytest.raises(StorageImportLimitExceededException, match="more than 2 files"):
            import_service.import_files(
                _ACTOR, acme.id, collection.collection_id, [_folder(acme, "big-folder/").id]
            )

    @override_settings(MAX_ARCHIVE_ENTRIES=1)
    def test_too_many_requested_ids_is_rejected_before_loading(
        self, import_service, acme, collection
    ):
        with pytest.raises(StorageImportLimitExceededException, match="more than 2"):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [1, 2, 3])

    @override_settings(MAX_UPLOAD_TOTAL_SIZE=10)
    def test_running_total_stops_downloads_when_the_index_understates_sizes(
        self, import_service, storage_manager, acme, collection
    ):
        grown = _store(storage_manager, acme, "grown.txt", b"x" * 20)
        StorageFile.objects.filter(id=grown.id).update(size=1)

        with pytest.raises(StorageImportLimitExceededException, match="over the limit"):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [grown.id])

        assert _document_names(collection) == []


class TestRecheckAtWriteTime:
    """A download hook changes the collection between the pre-download checks
    and the write, in the same transaction. This proves the duplicate and
    existence checks are repeated under the collection lock; it does not
    exercise two transactions actually blocking on that lock."""

    def test_duplicate_added_before_the_write_is_skipped(self, acme, collection):
        def add_same_file_before_write():
            if not DocumentMetadata.objects.filter(file_name="race.txt").exists():
                _existing_document(collection, "race.txt", b"race")

        storage_manager = StorageManager(_BackendWithDownloadHook(add_same_file_before_write))
        raced = _store(storage_manager, acme, "race.txt", b"race")
        calm = _store(storage_manager, acme, "calm.txt", b"calm")

        result = StorageDocumentImportService(storage_manager).import_files(
            _ACTOR, acme.id, collection.collection_id, [raced.id, calm.id]
        )

        assert [document.file_name for document in result.documents] == ["calm.txt"]
        assert result.skipped == [SkippedStorageFile(raced.id, "race.txt", SkipReason.DUPLICATE)]
        assert _document_names(collection) == ["calm.txt", "race.txt"]

    def test_every_file_duplicated_before_the_write_raises_nothing_to_import(
        self, acme, collection
    ):
        def add_same_file_before_write():
            if not DocumentMetadata.objects.filter(file_name="race.txt").exists():
                _existing_document(collection, "race.txt", b"race")

        storage_manager = StorageManager(_BackendWithDownloadHook(add_same_file_before_write))
        raced = _store(storage_manager, acme, "race.txt", b"race")

        with pytest.raises(NothingToImportException) as raised:
            StorageDocumentImportService(storage_manager).import_files(
                _ACTOR, acme.id, collection.collection_id, [raced.id]
            )

        assert raised.value.skipped == [
            SkippedStorageFile(raced.id, "race.txt", SkipReason.DUPLICATE)
        ]
        assert _document_names(collection) == ["race.txt"]

    @pytest.mark.parametrize("delete_mode", ["soft", "hard"])
    def test_collection_deleted_before_the_write_is_not_found(
        self, acme, collection, delete_mode
    ):
        def delete_collection_before_write():
            if SourceCollection.objects.filter(collection_id=collection.collection_id).exists():
                _delete_collection(collection, delete_mode)

        storage_manager = StorageManager(_BackendWithDownloadHook(delete_collection_before_write))
        stored = _store(storage_manager, acme, "late.txt", b"late")

        with pytest.raises(CollectionNotFoundException):
            StorageDocumentImportService(storage_manager).import_files(
                _ACTOR, acme.id, collection.collection_id, [stored.id]
            )

        assert not DocumentMetadata.objects.filter(file_name="late.txt").exists()


class TestAuditLog:
    def test_successful_import_logs_actor_org_collection_and_files(
        self, import_service, storage_manager, acme, collection, audit_log
    ):
        notes = _store(storage_manager, acme, "reports/notes.txt", b"secret quarterly figures")
        sheet = _store(storage_manager, acme, "reports/sheet.xlsx", b"xl")

        import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [notes.id, sheet.id]
        )

        [line] = _audit_lines(audit_log)
        assert _ACTOR in line
        assert f"in org {acme.id}" in line
        assert f"collection {collection.collection_id}" in line
        assert "(skipped 1)" in line
        assert f"({notes.id}, 'reports/notes.txt')" in line
        assert "sheet.xlsx" not in line
        assert "secret quarterly figures" not in line

    def test_logged_file_list_is_bounded(
        self, import_service, storage_manager, acme, collection, audit_log
    ):
        rows = [
            _store(storage_manager, acme, f"bulk/file{index:03}.txt", f"{index}".encode())
            for index in range(105)
        ]

        import_service.import_files(
            _ACTOR, acme.id, collection.collection_id, [row.id for row in rows]
        )

        # The project's stdout sink truncates messages over 200 characters
        # (utils.logger.truncate_filter) by rewriting the shared record, so
        # this also proves the audit line is exempt from that truncation.
        [line] = _audit_lines(audit_log)
        assert not line.endswith("...")
        assert "imported 105 storage file(s)" in line
        assert "first 100 of 105" in line
        assert "'bulk/file000.txt'" in line
        assert "'bulk/file099.txt'" in line
        assert "'bulk/file100.txt'" not in line

    def test_control_characters_in_a_path_cannot_forge_a_log_line(
        self, import_service, storage_manager, acme, collection, audit_log
    ):
        stored = _store(storage_manager, acme, "odd/a\nforged audit line.txt", b"x")

        import_service.import_files(_ACTOR, acme.id, collection.collection_id, [stored.id])

        [line] = _audit_lines(audit_log)
        assert "\n" not in line
        assert "\\n" in line

    def test_long_path_is_shortened_keeping_the_file_name(
        self, import_service, storage_manager, acme, collection, audit_log
    ):
        long_path = "deep/" + "nested-folder-name/" * 15 + "quarterly-report.txt"
        assert len(long_path) > 200
        stored = _store(storage_manager, acme, long_path, b"x")

        import_service.import_files(_ACTOR, acme.id, collection.collection_id, [stored.id])

        [line] = _audit_lines(audit_log)
        logged_path = line.split(f"({stored.id}, '", 1)[1].split("')", 1)[0]
        assert logged_path.startswith("…")
        assert logged_path.endswith("/quarterly-report.txt")
        assert len(logged_path) == 200
        assert long_path not in line

    def test_failed_import_writes_no_audit_line(
        self, import_service, storage_manager, acme, collection, audit_log
    ):
        sheet = _store(storage_manager, acme, "sheet.xlsx", b"xl")

        with pytest.raises(NothingToImportException):
            import_service.import_files(_ACTOR, acme.id, collection.collection_id, [sheet.id])

        assert _audit_lines(audit_log) == []


class TestShortenPathForLog:
    def test_path_at_the_limit_is_kept_whole(self):
        path = "a" * 196 + ".txt"

        assert _shorten_path_for_log(path) == path

    def test_path_over_the_limit_keeps_its_tail(self):
        path = "b" * 300 + "/report.txt"

        shortened = _shorten_path_for_log(path)

        assert shortened == "…" + path[-199:]
        assert len(shortened) == 200
        assert shortened.endswith("/report.txt")


class TestUploadNewFilesBatch:
    def test_skips_existing_and_in_batch_duplicates(self, collection):
        _existing_document(collection, "old.txt", b"old")
        existing_duplicate = SimpleUploadedFile("old.txt", b"old")
        first = SimpleUploadedFile("new.txt", b"new")
        in_batch_duplicate = SimpleUploadedFile("new.txt", b"new")

        created, duplicates = DocumentManagementService.upload_new_files_batch(
            collection.collection_id, [existing_duplicate, first, in_batch_duplicate]
        )

        assert [document.file_name for document in created] == ["new.txt"]
        assert duplicates == [existing_duplicate, in_batch_duplicate]
        assert _document_names(collection) == ["new.txt", "old.txt"]

    @pytest.mark.parametrize("delete_mode", ["soft", "hard"])
    def test_deleted_collection_raises_not_found(self, collection, delete_mode):
        _delete_collection(collection, delete_mode)

        with pytest.raises(CollectionNotFoundException):
            DocumentManagementService.upload_new_files_batch(
                collection.collection_id, [SimpleUploadedFile("a.txt", b"a")]
            )
