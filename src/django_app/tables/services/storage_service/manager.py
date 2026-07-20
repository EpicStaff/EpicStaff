import dataclasses
import io
import os
import tarfile
import zipfile
from typing import Iterator

from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.dataclasses import (
    ArchiveUploadResult,
    FileInfo,
    FileListItem,
    FileUploadResult,
    FolderInfo,
    TreeNode,
    UploadFileResult,
    UploadResult,
)
from tables.services.storage_service.db_sync import StorageFileSync


_DOCUMENT_EXTENSIONS = frozenset(
    {
        # Microsoft Office (OOXML)
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".docx",
        ".docm",
        ".dotx",
        ".pptx",
        ".pptm",
        ".ppsx",
        ".potx",
        # OpenDocument
        ".ods",
        ".odt",
        ".odp",
        ".odg",
        ".odf",
        ".ots",
        ".ott",
        ".otp",
        # Other ZIP-based formats that should not be extracted
        ".epub",
        ".apk",
        ".jar",
        ".war",
        ".xpi",
    }
)


class StorageManager:
    """
    Org-aware wrapper around AbstractStorageBackend.

    The backend must be initialized with organization_prefix="" so that path
    composition stays here, not inside the backend. This lets cross-org
    operations work naturally — source and destination keys can belong to
    different orgs without any backend changes.

    Authorization is enforced at the API layer (StorageAPIView:
    IsAuthenticated + HasOrgPermission(FILES) + active-org membership, and
    superadmin-only for cross-org transfers). This manager only composes
    org-scoped keys and delegates to the backend.
    """

    def __init__(self, backend: AbstractStorageBackend):
        self._backend = backend

    # --- Path helpers ---

    def _build_storage_key(self, org_id: int, relative_path: str) -> str:
        """Return the full storage key for a relative path inside an org."""
        return f"org_{org_id}/{relative_path.lstrip('/')}"

    def _strip_org_prefix(self, org_id: int, storage_key: str) -> str:
        """Convert a full storage key back to a relative path by removing the org prefix."""
        prefix = f"org_{org_id}/"
        if storage_key.startswith(prefix):
            return storage_key[len(prefix) :]
        return storage_key

    # --- Single-org operations ---

    def list_(self, org_id: int, prefix: str = "") -> list[FileListItem]:
        return self._backend.list_(self._build_storage_key(org_id, prefix))

    def upload(self, org_id: int, path: str, file_object) -> UploadResult:
        result = self._backend.upload(
            self._build_storage_key(org_id, path), file_object
        )
        relative_path = self._strip_org_prefix(org_id, result.path)
        StorageFileSync.on_upload(org_id, relative_path)
        return UploadResult(path=relative_path, size=result.size)

    def download(self, org_id: int, path: str) -> bytes:
        return self._backend.download(self._build_storage_key(org_id, path))

    def delete(self, org_id: int, path: str) -> None:
        self._backend.delete(self._build_storage_key(org_id, path))
        StorageFileSync.on_delete(org_id, path)

    def mkdir(self, org_id: int, path: str) -> None:
        self._backend.mkdir(self._build_storage_key(org_id, path))

    def move(self, org_id: int, source_path: str, destination_path: str) -> None:
        self._backend.move(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        StorageFileSync.on_move(org_id, source_path, destination_path)

    def rename(self, org_id: int, source_path: str, destination_path: str) -> None:
        self._backend.rename(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        StorageFileSync.on_move(org_id, source_path, destination_path)

    def copy(self, org_id: int, source_path: str, destination_path: str) -> None:
        actual_keys = self._backend.copy(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        actual_paths = [self._strip_org_prefix(org_id, k) for k in actual_keys]
        StorageFileSync.on_copy(org_id, actual_paths)

    def info(self, org_id: int, path: str) -> FileInfo | FolderInfo:
        result = self._backend.info(self._build_storage_key(org_id, path))
        return dataclasses.replace(
            result, path=self._strip_org_prefix(org_id, result.path)
        )

    def exists(self, org_id: int, path: str) -> bool:
        return self._backend.exists(self._build_storage_key(org_id, path))

    def download_zip(self, org_id: int, paths: list[str]) -> Iterator[bytes]:
        """
        Yield a zip archive of the given paths.
        Zip entry names are relative (no org prefix) so callers don't see
        internal storage structure inside the archive.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                storage_key = self._build_storage_key(org_id, path)
                item_info = self._backend.info(storage_key)
                if isinstance(item_info, FolderInfo):
                    for key in self._backend.list_all_keys(storage_key):
                        file_bytes = self._backend.download(key)
                        archive_name = self._strip_org_prefix(org_id, key)
                        archive.writestr(archive_name.lstrip("/"), file_bytes)
                else:
                    file_bytes = self._backend.download(storage_key)
                    archive.writestr(path.lstrip("/"), file_bytes)
        buffer.seek(0)
        yield buffer.read()

    def _upload_archive(self, org_id: int, prefix: str, archive_file) -> list[str]:
        """Extract archive into prefix. Returns relative paths (no org prefix)."""
        full_paths = self._backend.upload_archive(
            self._build_storage_key(org_id, prefix), archive_file, archive_file.name
        )
        return [self._strip_org_prefix(org_id, p) for p in full_paths]

    @staticmethod
    def _is_archive(file_object, filename: str = "") -> bool:
        ext = os.path.splitext(filename)[1].lower()
        if ext in _DOCUMENT_EXTENSIONS:
            return False
        pos = file_object.tell()
        result = zipfile.is_zipfile(file_object)
        if not result:
            file_object.seek(pos)
            try:
                result = tarfile.is_tarfile(file_object)
            except Exception:
                result = False
        file_object.seek(pos)
        return result

    def upload_file(self, org_id: int, path: str, file_object) -> UploadFileResult:
        """
        Upload a file, auto-extracting archives (ZIP/TAR).
        Returns FileUploadResult or ArchiveUploadResult.
        """
        is_archive = self._is_archive(file_object, filename=file_object.name)

        if is_archive:
            extracted = self._upload_archive(org_id, path, file_object)

            for p in extracted:
                StorageFileSync.on_upload(org_id, p)

            return ArchiveUploadResult(type="archive", extracted=extracted)

        destination = (
            f"{path.rstrip('/')}/{file_object.name}" if path else file_object.name
        )
        result = self._backend.upload(
            self._build_storage_key(org_id, destination), file_object
        )
        relative_path = self._strip_org_prefix(org_id, result.path)
        StorageFileSync.on_upload(org_id, relative_path)
        return FileUploadResult(type="file", path=relative_path, size=result.size)

    def list_tree(
        self,
        org_id: int,
        prefix: str = "",
        max_depth: int | None = None,
        max_entries: int = 50_000,
    ) -> tuple[TreeNode, bool]:
        root, truncated = self._backend.list_tree(
            self._build_storage_key(org_id, prefix), max_depth, max_entries
        )
        return self._strip_tree_org_prefix(org_id, root), truncated

    def _strip_tree_org_prefix(self, org_id: int, node: TreeNode) -> TreeNode:
        stripped_path = self._strip_org_prefix(org_id, node.path)
        children = (
            None
            if node.children is None
            else [self._strip_tree_org_prefix(org_id, child) for child in node.children]
        )
        return dataclasses.replace(node, path=stripped_path, children=children)

    def search(
        self,
        org_id: int,
        q: str,
        path: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Substring search on filename within an org."""
        from tables.models import StorageFile

        qs = StorageFile.objects.filter(org_id=org_id, name__icontains=q)

        if path:
            qs = qs.filter(path__startswith=path.rstrip("/") + "/")

        total = qs.count()
        rows = list(qs.order_by("path").values("path", "name")[offset : offset + limit])
        return rows, total

    # --- Cross-org operations (superadmin-only; enforced at the API layer) ---

    def copy_cross_org(
        self,
        src_org_id: int,
        src_path: str,
        dst_org_id: int,
        dst_path: str,
    ) -> None:
        """
        Copy a file from one org to another. Caller authorization (superadmin)
        is enforced at the API layer. Uses a server-side S3 copy — no data
        streams through the app.
        """
        actual_keys = self._backend.copy(
            self._build_storage_key(src_org_id, src_path),
            self._build_storage_key(dst_org_id, dst_path),
        )
        for key in actual_keys:
            actual_dst_path = self._strip_org_prefix(dst_org_id, key)
            StorageFileSync.on_copy_cross_org(dst_org_id, actual_dst_path)

    def move_cross_org(
        self,
        src_org_id: int,
        src_path: str,
        dst_org_id: int,
        dst_path: str,
    ) -> None:
        """
        Move a file from one org to another. Caller authorization (superadmin)
        is enforced at the API layer. Non-atomic: if the delete step fails after
        a successful copy, the file will exist in both orgs.
        """
        self._backend.move(
            self._build_storage_key(src_org_id, src_path),
            self._build_storage_key(dst_org_id, dst_path),
        )
        StorageFileSync.on_move_cross_org(src_org_id, src_path, dst_org_id, dst_path)
