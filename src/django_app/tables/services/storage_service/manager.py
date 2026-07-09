import dataclasses
import io
import mimetypes
import os
import tarfile
import zipfile
from typing import Iterator

from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
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
        rows = list(
            StorageFile.objects.filter(org_id=org_id, parent_path=norm).order_by(
                Case(
                    When(item_type="folder", then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
                Lower("name"),
            )
        )

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
        clean_path = path.rstrip("/")
        file_exists = StorageFile.objects.filter(
            org_id=org_id, path=clean_path, item_type="file"
        ).exists()
        if not file_exists:
            raise FileNotFoundError(f"File does not exist: {path}")
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
        actual_key = self._backend.move(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        actual_path = self._strip_org_prefix(org_id, actual_key)
        StorageFileSync.on_move(org_id, source_path, actual_path)

    @check_permission
    def rename(
        self, user_name: str, org_id: int, source_path: str, destination_path: str
    ) -> None:
        destination_clean = destination_path.rstrip("/")
        destination_exists = StorageFile.objects.filter(
            org_id=org_id, path__in=[destination_clean, destination_clean + "/"]
        ).exists()
        if destination_exists:
            raise FileExistsError(f"Destination already exists: {destination_path}")

        self._backend.rename(
            self._build_storage_key(org_id, source_path),
            self._build_storage_key(org_id, destination_path),
        )
        # rename never dedupes — the guard above confirmed this exact path was
        # free, so destination_path IS the actual path (unlike move).
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
    ) -> tuple[str, Iterator[bytes]]:
        """
        Resolve the zip filename and archive entries eagerly (DB-first), then
        return the resolved filename alongside a generator that streams the
        archive bytes.

        Naming rule:
          - Single folder: zip named "<folder name>.zip"; entries are
            relative to the folder (folder contents sit at the zip root, no
            wrapper directory).
          - Single file: zip named "<file name>.zip"; entry is the bare file
            name.
          - Multiple paths: zip named "download.zip"; entries keep their
            full org-relative path.
        """
        single_path = len(paths) == 1
        entries: list[tuple[str, str]] = []  # (storage_path, arcname)
        resolved_row = None

        for path in paths:
            clean_path = path.rstrip("/")
            row = StorageFile.objects.filter(
                org_id=org_id, path__in=[clean_path, clean_path + "/"]
            ).first()
            if row is None:
                raise FileNotFoundError(f"Path does not exist: {path}")

            resolved_row = row

            if row.item_type == "folder":
                file_rows = StorageFile.objects.filter(
                    org_id=org_id, path__startswith=row.path, item_type="file"
                )
                for file_row in file_rows:
                    arcname = (
                        file_row.path[len(row.path) :]
                        if single_path
                        else file_row.path.lstrip("/")
                    )
                    entries.append((file_row.path, arcname))
            else:
                arcname = row.name if single_path else row.path.lstrip("/")
                entries.append((row.path, arcname))

        zip_filename = f"{resolved_row.name}.zip" if single_path else "download.zip"
        return zip_filename, self._stream_zip(org_id, entries)

    def _stream_zip(
        self, org_id: int, entries: list[tuple[str, str]]
    ) -> Iterator[bytes]:
        """Build a zip archive in memory from resolved (storage_path, arcname) entries."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for storage_path, arcname in entries:
                file_bytes = self._backend.download(
                    self._build_storage_key(org_id, storage_path)
                )
                archive.writestr(arcname, file_bytes)
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
            if node_dict["children_map"] is None:
                children = None
            else:
                sorted_children = sorted(
                    node_dict["children_map"].values(),
                    key=lambda n: (n["type"] != "folder", n["name"].lower()),
                )
                children = [build(child) for child in sorted_children]
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
        actual_dst_paths = [self._strip_org_prefix(dst_org_id, k) for k in actual_keys]
        StorageFileSync.on_copy(dst_org_id, actual_dst_paths)

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
        actual_key = self._backend.move(
            self._build_storage_key(src_org_id, src_path),
            self._build_storage_key(dst_org_id, dst_path),
        )
        actual_dst_path = self._strip_org_prefix(dst_org_id, actual_key)
        StorageFileSync.on_move_cross_org(
            src_org_id, src_path, dst_org_id, actual_dst_path
        )
