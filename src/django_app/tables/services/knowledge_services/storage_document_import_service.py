import operator
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from loguru import logger
from tables.constants.upload_limits import UploadLimits, default_upload_limits
from tables.exceptions import (
    FileSizeExceededException,
    InvalidFileTypeException,
    NothingToImportException,
    StorageFilesNotFoundException,
    StorageImportLimitExceededException,
)
from tables.models import DocumentMetadata, StorageFile
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.storage_service.manager import StorageManager

# A selection may hold this many candidate files per importable one, so a
# folder with some unsupported or duplicate files still imports, while the
# rows loaded (and the `skipped` list returned) stay bounded.
_CANDIDATES_PER_IMPORTABLE_FILE = 2

_STORAGE_ROW_FIELDS = ("id", "path", "name", "item_type", "size")

# How many imported files the audit log line lists by id and path, and how
# many characters of each path it keeps: together they bound the line at ~21 KB.
_AUDIT_LOGGED_FILES_LIMIT = 100
_AUDIT_LOGGED_PATH_LENGTH = 200


def _shorten_path_for_log(path: str) -> str:
    """Keep the tail of an over-long path: the file name is the useful part."""
    if len(path) <= _AUDIT_LOGGED_PATH_LENGTH:
        return path
    return "…" + path[-(_AUDIT_LOGGED_PATH_LENGTH - 1) :]


def max_storage_selection(limits: UploadLimits | None = None) -> int:
    """Return how many storage ids, or files after folder expansion, one import may select."""
    limits = limits or default_upload_limits()
    return limits.max_archive_entries * _CANDIDATES_PER_IMPORTABLE_FILE


class SkipReason(StrEnum):
    UNSUPPORTED_TYPE = "unsupported_type"
    TOO_LARGE = "too_large"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class SkippedStorageFile:
    storage_file_id: int
    path: str
    reason: SkipReason

    def to_dict(self) -> dict:
        return {
            "storage_file_id": self.storage_file_id,
            "path": self.path,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class StorageImportResult:
    documents: list[DocumentMetadata]
    skipped: list[SkippedStorageFile]


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A storage file selected for import, with its size known."""

    storage_file_id: int
    path: str
    name: str
    size: int


class StorageDocumentImportService:
    """Import files from an organization's storage into a knowledge source collection.

    Coordinates only: the storage manager owns the bytes and
    ``DocumentManagementService`` owns creating documents, so an import goes
    through exactly the same validation and transaction as a browser upload.
    """

    def __init__(self, storage_manager: StorageManager):
        self._storage_manager = storage_manager

    def import_files(
        self,
        actor: str,
        org_id: int,
        collection_id: int,
        storage_file_ids: list[int],
    ) -> StorageImportResult:
        """Copy the selected storage files into a collection as new documents.

        Folders are expanded to every non-system file beneath them. Files the
        collection cannot take (unsupported type, too large, or already present
        with the same name and size) are skipped rather than failing the import.
        Unsupported types are dropped first; the remaining files are then held
        to the count limit — including ones later skipped as too large or
        duplicate, since telling needs their size — before any size the index
        lacks is read from the object store. The total-size limit is checked
        before any bytes are downloaded. Size lookups and downloads run one at a
        time; the count limit bounds that latency. Indexing is not started.

        Args:
            actor: Who is importing, as an audit label built by the caller
                (e.g. ``"user:5"`` or ``"system api_key:12"``). Recorded in the
                audit log line written after a successful import.
            org_id: The caller's active organization; every storage id must belong to it.
            collection_id: Target collection. The caller must already have
                verified it belongs to ``org_id``.
            storage_file_ids: Ids of files and/or folders.

        Raises:
            StorageFilesNotFoundException: An id is missing, in another org, or a
                system file — or a file's bytes are gone from the object store.
            NothingToImportException: Every selected file was skipped.
            StorageImportLimitExceededException: Too many files or bytes selected.
            CollectionNotFoundException: The collection was deleted during the import.
            DocumentUploadException: ``FileValidator`` rejected the downloaded files.
        """
        limits = default_upload_limits()
        max_candidates = max_storage_selection(limits)

        requested_rows = self._load_requested_rows(org_id, storage_file_ids, max_candidates)
        file_rows = self._expand_folders(org_id, requested_rows, max_candidates)
        supported_rows, skipped = self._drop_unsupported_types(file_rows)
        self._check_file_count(supported_rows, limits)

        candidates = [self._with_known_size(org_id, row) for row in supported_rows]
        importable, size_or_duplicate_skips = self._split_importable(collection_id, candidates)
        skipped.extend(size_or_duplicate_skips)

        if not importable:
            raise NothingToImportException(skipped)

        self._check_total_size(importable, limits)
        downloads = self._download_all(org_id, importable, limits)

        documents, duplicate_files = DocumentManagementService.upload_new_files_batch(
            collection_id=collection_id, uploaded_files=list(downloads)
        )
        # Another import may have added the same files since the first check.
        skipped.extend(
            SkippedStorageFile(
                storage_file_id=downloads[duplicate].storage_file_id,
                path=downloads[duplicate].path,
                reason=SkipReason.DUPLICATE,
            )
            for duplicate in duplicate_files
        )
        if not documents:
            raise NothingToImportException(skipped)

        duplicates_at_write = set(duplicate_files)
        imported = [
            candidate
            for uploaded_file, candidate in downloads.items()
            if uploaded_file not in duplicates_at_write
        ]
        self._log_import(actor, org_id, collection_id, imported, len(skipped))
        return StorageImportResult(documents=documents, skipped=skipped)

    @staticmethod
    def _log_import(
        actor: str,
        org_id: int,
        collection_id: int,
        imported: list[_Candidate],
        skipped_count: int,
    ) -> None:
        # Audit record: who copied which storage files into which collection.
        # Ids and paths only, never contents. The list is bounded; the tuples
        # render with repr(), so control characters in a path are escaped
        # rather than forging extra log lines. bind(audit=True) exempts the
        # line from the stdout sink's 200-character truncation
        # (utils.logger.truncate_filter), which would otherwise drop the ids.
        logged_files = [
            (candidate.storage_file_id, _shorten_path_for_log(candidate.path))
            for candidate in imported[:_AUDIT_LOGGED_FILES_LIMIT]
        ]
        logger.bind(audit=True).info(
            "Storage import: {} in org {} imported {} storage file(s) into "
            "collection {} (skipped {}); files (storage_file_id, path), first {} of {}: {}",
            actor,
            org_id,
            len(imported),
            collection_id,
            skipped_count,
            len(logged_files),
            len(imported),
            logged_files,
        )

    @staticmethod
    def _load_requested_rows(
        org_id: int, storage_file_ids: list[int], max_candidates: int
    ) -> list[StorageFile]:
        unique_ids = set(storage_file_ids)
        if len(unique_ids) > max_candidates:
            raise StorageImportLimitExceededException(
                f"Cannot select more than {max_candidates} storage items at once"
            )

        rows = list(
            StorageFile.objects.filter(org_id=org_id, id__in=unique_ids, is_system=False).only(
                *_STORAGE_ROW_FIELDS
            )
        )
        # One generic 404 for the whole request, so the response never tells
        # which of the ids exists in another organization.
        if len(rows) != len(unique_ids):
            raise StorageFilesNotFoundException()
        return rows

    @staticmethod
    def _expand_folders(
        org_id: int, requested_rows: list[StorageFile], max_candidates: int
    ) -> list[StorageFile]:
        rows_by_id = {row.id: row for row in requested_rows if row.item_type == "file"}
        folder_paths = [row.path for row in requested_rows if row.item_type == "folder"]

        if folder_paths:
            under_any_folder = reduce(
                operator.or_, (Q(path__startswith=path) for path in folder_paths)
            )
            nested_files = (
                StorageFile.objects.filter(
                    under_any_folder, org_id=org_id, item_type="file", is_system=False
                )
                .only(*_STORAGE_ROW_FIELDS)
                .order_by("path")[: max_candidates + 1]
            )
            rows_by_id.update((row.id, row) for row in nested_files)

        if len(rows_by_id) > max_candidates:
            raise StorageImportLimitExceededException(
                f"The selection contains more than {max_candidates} files; "
                f"narrow it down and import at most {max_candidates} at once"
            )

        return sorted(rows_by_id.values(), key=lambda row: row.path)

    @staticmethod
    def _drop_unsupported_types(
        file_rows: list[StorageFile],
    ) -> tuple[list[StorageFile], list[SkippedStorageFile]]:
        supported_rows: list[StorageFile] = []
        skipped: list[SkippedStorageFile] = []
        for row in file_rows:
            try:
                DocumentManagementService.validate_file_type(row.name)
            except InvalidFileTypeException:
                skipped.append(
                    SkippedStorageFile(
                        storage_file_id=row.id, path=row.path, reason=SkipReason.UNSUPPORTED_TYPE
                    )
                )
            else:
                supported_rows.append(row)
        return supported_rows, skipped

    @staticmethod
    def _check_file_count(supported_rows: list[StorageFile], limits: UploadLimits) -> None:
        # Checked before any size lookup, so the lookups are bounded by the
        # same limit as the downloads.
        if len(supported_rows) > limits.max_archive_entries:
            raise StorageImportLimitExceededException(
                f"Cannot import {len(supported_rows)} files at once; "
                f"the limit is {limits.max_archive_entries}"
            )

    def _with_known_size(self, org_id: int, row: StorageFile) -> _Candidate:
        size = row.size
        if size is None:
            # The index has no size for some rows (StorageFileSync.on_copy
            # records none); trusting 0 would let any file past the limits.
            try:
                size = self._storage_manager.object_size(org_id, row.path)
            except FileNotFoundError as error:
                raise self._missing_object(org_id, row.id, row.path) from error
        return _Candidate(storage_file_id=row.id, path=row.path, name=row.name, size=size)

    @staticmethod
    def _split_importable(
        collection_id: int, candidates: list[_Candidate]
    ) -> tuple[list[_Candidate], list[SkippedStorageFile]]:
        taken_name_sizes = set(
            DocumentMetadata.objects.filter(source_collection_id=collection_id).values_list(
                "file_name", "file_size"
            )
        )

        importable: list[_Candidate] = []
        skipped: list[SkippedStorageFile] = []
        for candidate in candidates:
            reason = StorageDocumentImportService._skip_reason(candidate, taken_name_sizes)
            if reason is None:
                importable.append(candidate)
                # Two storage files with the same name and size in different
                # folders would become duplicates of each other in the collection.
                taken_name_sizes.add((candidate.name, candidate.size))
            else:
                skipped.append(
                    SkippedStorageFile(
                        storage_file_id=candidate.storage_file_id,
                        path=candidate.path,
                        reason=reason,
                    )
                )

        return importable, skipped

    @staticmethod
    def _skip_reason(
        candidate: _Candidate, taken_name_sizes: set[tuple[str, int]]
    ) -> SkipReason | None:
        # The type was already screened by _drop_unsupported_types.
        try:
            DocumentManagementService.validate_file_metadata(candidate.name, candidate.size)
        except FileSizeExceededException:
            return SkipReason.TOO_LARGE

        if (candidate.name, candidate.size) in taken_name_sizes:
            return SkipReason.DUPLICATE
        return None

    @staticmethod
    def _check_total_size(importable: list[_Candidate], limits: UploadLimits) -> None:
        total_bytes = sum(candidate.size for candidate in importable)
        if total_bytes > limits.max_total_bytes:
            raise StorageImportLimitExceededException(
                f"Total import size is {total_bytes} bytes, over the limit of "
                f"{limits.max_total_bytes} bytes"
            )

    def _download_all(
        self, org_id: int, importable: list[_Candidate], limits: UploadLimits
    ) -> dict[SimpleUploadedFile, _Candidate]:
        # Keyed by the file object itself (identity hash), so duplicates that
        # upload_new_files_batch hands back map to their storage rows.
        downloads: dict[SimpleUploadedFile, _Candidate] = {}
        downloaded_bytes = 0
        for candidate in importable:
            try:
                content = self._storage_manager.download(org_id, candidate.path)
            except FileNotFoundError as error:
                raise self._missing_object(
                    org_id, candidate.storage_file_id, candidate.path
                ) from error

            # The index can understate a size (the object changed after it was
            # indexed), so the pre-download total alone does not bound memory.
            # This bounds the running sum of downloaded bytes: at most the
            # budget plus one object, since each object is read whole before
            # it is counted. A single object is not capped.
            downloaded_bytes += len(content)
            if downloaded_bytes > limits.max_total_bytes:
                raise StorageImportLimitExceededException(
                    f"Total import size is over the limit of {limits.max_total_bytes} bytes"
                )
            downloads[SimpleUploadedFile(candidate.name, content)] = candidate
        return downloads

    @staticmethod
    def _missing_object(
        org_id: int, storage_file_id: int, path: str
    ) -> StorageFilesNotFoundException:
        # The index row exists but the object does not (drift, or deleted
        # concurrently). Report it like any other missing id.
        logger.warning(
            "Storage file {} ({}) has no object in org {}", storage_file_id, path, org_id
        )
        return StorageFilesNotFoundException()
