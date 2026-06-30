import dataclasses
import io
import mimetypes
import os
import tarfile
import zipfile
from typing import Iterator

from rest_framework.exceptions import PermissionDenied

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
from tables.services.storage_service.decorators import check_permission
from tables.services.storage_service.enums import StorageAction

from tables.models import OrganizationUser, StorageFile


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

    Every public method checks permissions via _require_permission before
    touching storage. Extend that method to add roles, path ACLs, audit
    logging, or any other access control logic.
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

    # --- Permission gate ---

    def _require_permission(
        self, user_name: str, org_id: int, action: StorageAction, path: str
    ) -> None:
        """
        Verify that user_name may perform action on path within org_id.

        Currently checks org membership only. This is the single extension
        point for all future access control:
          - Add role lookups to restrict actions (e.g. viewers cannot delete)
          - Add path-based ACLs for fine-grained file access
          - Add audit logging here to capture every storage operation
        """

        if not OrganizationUser.objects.filter(org_id=org_id).exists():
            raise PermissionDenied(
                f"User '{user_name}' does not have '{action}' permission "
                f"in organization {org_id}."
            )

        # Future: role = OrganizationUser.objects.get(...).role
        # Future: if not role.allows(action): raise PermissionDenied(...)
        # Future: if not path_acl_allows(role, path): raise PermissionDenied(...)

    # --- Single-org operations ---

    @check_permission
    def list_(
        self, user_name: str, org_id: int, prefix: str = ""
    ) -> list[FileListItem]:
        norm = (prefix.rstrip("/") + "/") if prefix else ""
        rows = list(StorageFile.objects.filter(org_id=org_id, parent_path=norm))

        folder_paths = [row.path for row in rows if row.item_type == "folder"]
        non_empty: set[str] = set()

        if folder_paths:
            non_empty = set(
                StorageFile.objects.filter(
                    org_id=org_id, parent_path__in=folder_paths
                ).values_list("parent_path", flat=True)
            )

        items = []
        for row in rows:
            if row.item_type == "folder":
                items.append(
                    FileListItem(
                        id=row.id,
                        name=row.name,
                        type="folder",
                        size=row.size or 0,
                        modified=row.s3_modified.isoformat()
                        if row.s3_modified
                        else None,
                        is_empty=row.path not in non_empty,
                    )
                )
            else:
                items.append(
                    FileListItem(
                        id=row.id,
                        name=row.name,
                        type="file",
                        size=row.size or 0,
                        modified=row.s3_modified.isoformat()
                        if row.s3_modified
                        else None,
                        is_empty=False,
                    )
                )

        return items

    @check_permission
    def upload(
        self, user_name: str, org_id: int, path: str, file_object
    ) -> UploadResult:
        result = self._backend.upload(
            self._build_storage_key(org_id, path), file_object
        )
        relative_path = self._strip_org_prefix(org_id, result.path)
        StorageFileSync.on_upload(org_id, relative_path, size=result.size)
        return UploadResult(path=relative_path, size=result.size)

    @check_permission
    def download(self, user_name: str, org_id: int, path: str) -> bytes:
        return self._backend.download(self._build_storage_key(org_id, path))

    @check_permission
    def delete(self, user_name: str, org_id: int, path: str) -> None:
        self._backend.delete(self._build_storage_key(org_id, path))
        StorageFileSync.on_delete(org_id, path)

    @check_permission
    def mkdir(self, user_name: str, org_id: int, path: str) -> None:
        self._backend.mkdir(self._build_storage_key(org_id, path))
        StorageFileSync.on_mkdir(org_id, path)

    @check_permission
    def move(
        self, user_name: str, org_id: int, source_path: str, destination_path: str
    ) -> None:
        self._backend.move(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        StorageFileSync.on_move(org_id, source_path, destination_path)

    @check_permission
    def rename(
        self, user_name: str, org_id: int, source_path: str, destination_path: str
    ) -> None:
        self._backend.rename(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        StorageFileSync.on_move(org_id, source_path, destination_path)

    @check_permission
    def copy(
        self, user_name: str, org_id: int, source_path: str, destination_path: str
    ) -> None:
        actual_keys = self._backend.copy(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        actual_paths = [self._strip_org_prefix(org_id, k) for k in actual_keys]
        StorageFileSync.on_copy(org_id, actual_paths)

    @check_permission
    def info(self, user_name: str, org_id: int, path: str) -> FileInfo | FolderInfo:
        clean_path = path.rstrip("/")
        try:
            row = StorageFile.objects.get(org_id=org_id, path=clean_path)
            content_type, _ = mimetypes.guess_type(row.name)
            return FileInfo(
                id=row.id,
                name=row.name,
                path=row.path,
                size=row.size or 0,
                content_type=content_type or "application/octet-stream",
                modified=(row.s3_modified or row.created_at).isoformat(),
            )
        except StorageFile.DoesNotExist:
            pass

        folder_path = clean_path + "/"
        try:
            row = StorageFile.objects.get(org_id=org_id, path=folder_path)
            return FolderInfo(
                id=row.id,
                name=row.name,
                path=row.path,
                modified=(row.s3_modified or row.created_at).isoformat(),
            )
        except StorageFile.DoesNotExist:
            pass

        raise FileNotFoundError(f"File does not exist: {path}")

    @check_permission
    def exists(self, user_name: str, org_id: int, path: str) -> bool:
        return self._backend.exists(self._build_storage_key(org_id, path))

    @check_permission
    def download_zip(
        self, user_name: str, org_id: int, paths: list[str]
    ) -> Iterator[bytes]:
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

    def upload_file(
        self, user_name: str, org_id: int, path: str, file_object
    ) -> UploadFileResult:
        """
        Upload a file, auto-extracting archives (ZIP/TAR).
        Returns FileUploadResult or ArchiveUploadResult.
        """
        is_archive = self._is_archive(file_object, filename=file_object.name)

        if is_archive:
            self._require_permission(
                user_name, org_id, action=StorageAction.UPLOAD, path=path
            )
            extracted = self._upload_archive(org_id, path, file_object)

            for p in extracted:
                StorageFileSync.on_upload(org_id, p)

            return ArchiveUploadResult(type="archive", extracted=extracted)

        destination = (
            f"{path.rstrip('/')}/{file_object.name}" if path else file_object.name
        )
        self._require_permission(
            user_name, org_id, action=StorageAction.UPLOAD, path=destination
        )
        result = self._backend.upload(
            self._build_storage_key(org_id, destination), file_object
        )
        relative_path = self._strip_org_prefix(org_id, result.path)
        StorageFileSync.on_upload(org_id, relative_path, size=result.size)
        return FileUploadResult(type="file", path=relative_path, size=result.size)

    @check_permission
    def list_tree(
        self,
        user_name: str,
        org_id: int,
        prefix: str = "",
        max_depth: int | None = None,
        max_entries: int = 50_000,
    ) -> tuple[TreeNode, bool]:
        norm = (prefix.rstrip("/") + "/") if prefix else ""
        root_name = prefix.rstrip("/").split("/")[-1] if prefix else ""

        root_dict: dict = {
            "id": None,
            "name": root_name,
            "path": norm,
            "type": "folder",
            "size": 0,
            "modified": None,
            "children_map": {},
        }
        nodes_by_path: dict[str, dict] = {norm: root_dict}
        truncated = False
        count = 0

        rows = StorageFile.objects.filter(
            org_id=org_id, path__startswith=norm
        ).order_by("path")

        for row in rows:
            if row.path == norm:
                continue

            rel = row.path[len(norm) :]
            parts = rel.rstrip("/").split("/") if rel.rstrip("/") else []
            depth = len(parts)

            is_folder = row.item_type == "folder"

            if max_depth is not None and depth > max_depth:
                parts = parts[:max_depth]
                depth = max_depth
                is_folder = True

            cur_path = norm
            parent = nodes_by_path[cur_path]
            broken = False

            for segment in parts[:-1]:
                cur_path = cur_path + segment + "/"
                if cur_path not in nodes_by_path:
                    if count >= max_entries:
                        truncated = True
                        broken = True
                        break
                    node = {
                        "id": None,
                        "name": segment,
                        "path": cur_path,
                        "type": "folder",
                        "size": 0,
                        "modified": None,
                        "children_map": {},
                    }
                    nodes_by_path[cur_path] = node
                    parent["children_map"][segment] = node
                    count += 1
                parent = nodes_by_path[cur_path]

            if broken:
                break

            leaf_name = parts[-1] if parts else ""
            if not leaf_name:
                continue

            leaf_path = cur_path + leaf_name + ("/" if is_folder else "")
            if leaf_path in nodes_by_path:
                continue

            if count >= max_entries:
                truncated = True
                break

            if is_folder:
                node = {
                    "id": row.id,
                    "name": leaf_name,
                    "path": leaf_path,
                    "type": "folder",
                    "size": 0,
                    "modified": row.s3_modified.isoformat()
                    if row.s3_modified
                    else None,
                    "children_map": {},
                }
            else:
                node = {
                    "id": row.id,
                    "name": leaf_name,
                    "path": leaf_path,
                    "type": "file",
                    "size": row.size or 0,
                    "modified": row.s3_modified.isoformat()
                    if row.s3_modified
                    else None,
                    "children_map": None,
                }

            nodes_by_path[leaf_path] = node
            parent["children_map"][leaf_name] = node
            count += 1

        def build(node_dict: dict) -> TreeNode:
            children = (
                None
                if node_dict["children_map"] is None
                else [build(child) for child in node_dict["children_map"].values()]
            )
            return TreeNode(
                id=node_dict["id"],
                name=node_dict["name"],
                path=node_dict["path"],
                type=node_dict["type"],
                size=node_dict["size"],
                modified=node_dict["modified"],
                children=children,
            )

        return build(root_dict), truncated

    @check_permission
    def search(
        self,
        user_name: str,
        org_id: int,
        q: str,
        path: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Substring search on filename within an org."""
        qs = StorageFile.objects.filter(
            org_id=org_id, name__icontains=q, item_type="file"
        )

        if path:
            qs = qs.filter(path__startswith=path.rstrip("/") + "/")

        total = qs.count()
        rows = list(
            qs.order_by("path").values("id", "path", "name")[offset : offset + limit]
        )
        return rows, total

    # --- Cross-org operations ---

    def copy_cross_org(
        self,
        user_name: str,
        src_org_id: int,
        src_path: str,
        dst_org_id: int,
        dst_path: str,
    ) -> None:
        """
        Copy a file from one org to another. User must have permission in both.
        Uses a server-side S3 copy — no data streams through the app.
        """
        self._require_permission(
            user_name, src_org_id, action=StorageAction.DOWNLOAD, path=src_path
        )
        self._require_permission(
            user_name, dst_org_id, action=StorageAction.UPLOAD, path=dst_path
        )
        actual_keys = self._backend.copy(
            self._build_storage_key(src_org_id, src_path),
            self._build_storage_key(dst_org_id, dst_path),
        )
        for key in actual_keys:
            actual_dst_path = self._strip_org_prefix(dst_org_id, key)
            StorageFileSync.on_copy_cross_org(dst_org_id, actual_dst_path)

    def move_cross_org(
        self,
        user_name: str,
        src_org_id: int,
        src_path: str,
        dst_org_id: int,
        dst_path: str,
    ) -> None:
        """
        Move a file from one org to another. User must have permission in both.
        Non-atomic: if the delete step fails after a successful copy, the file
        will exist in both orgs.
        """
        self._require_permission(
            user_name, src_org_id, action=StorageAction.DELETE, path=src_path
        )
        self._require_permission(
            user_name, dst_org_id, action=StorageAction.UPLOAD, path=dst_path
        )
        self._backend.move(
            self._build_storage_key(src_org_id, src_path),
            self._build_storage_key(dst_org_id, dst_path),
        )
        StorageFileSync.on_move_cross_org(src_org_id, src_path, dst_org_id, dst_path)
