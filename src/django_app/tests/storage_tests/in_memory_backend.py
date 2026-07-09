import io
import mimetypes
import zipfile
from datetime import datetime, timezone
from typing import Iterator

from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FolderInfo,
    FileListItem,
    TreeNode,
    UploadResult,
)


class InMemoryStorageBackend(AbstractStorageBackend):
    """
    In-memory fake standing in for S3StorageBackend in tests.

    Mirrors S3 key semantics: everything is a flat dict of full key -> (bytes,
    modified datetime). Folders have no real existence — they are either a
    zero-byte marker key ending in "/" (created by mkdir) or implied by files
    living under a common prefix (a "virtual folder").
    """

    def __init__(self, organization_prefix: str = ""):
        self.organization_prefix = organization_prefix
        self._objects: dict[str, tuple[bytes, datetime]] = {}

    def _full_path(self, path: str) -> str:
        """Prepend the organization prefix to a caller-provided path."""
        return self.organization_prefix + path.lstrip("/")

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the organization prefix from a stored key."""
        if full_key.startswith(self.organization_prefix):
            return full_key[len(self.organization_prefix) :]
        return full_key

    def _key_exists(self, key: str, is_folder: bool) -> bool:
        if is_folder:
            folder_prefix = key if key.endswith("/") else key + "/"
            if folder_prefix in self._objects:
                return True
            return any(k.startswith(folder_prefix) for k in self._objects)
        return key in self._objects

    def _unique_key(self, key: str, is_folder: bool = False) -> str:
        """Increment the name segment of *key* until nothing exists at that path."""
        if not self._key_exists(key, is_folder):
            return key
        parts = key.rstrip("/").rsplit("/", 1)
        parent = parts[0] + "/" if len(parts) > 1 else ""
        name = parts[-1]
        while True:
            name = self._increment_name(name, is_folder=is_folder)
            candidate = parent + name
            if not self._key_exists(candidate, is_folder):
                return candidate

    # --- Basic operations ---

    def upload(self, path: str, file_object) -> UploadResult:
        full_path = self._full_path(path)
        content = file_object.read()
        self._objects[full_path] = (content, datetime.now(timezone.utc))
        return UploadResult(path=path, size=len(content))

    def download(self, path: str) -> bytes:
        full_path = self._full_path(path)
        if full_path not in self._objects:
            raise FileNotFoundError(f"File does not exist: {path}")
        return self._objects[full_path][0]

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)
        if full_path in self._objects:
            del self._objects[full_path]
            return

        prefix = full_path if full_path.endswith("/") else full_path + "/"
        for key in [k for k in self._objects if k.startswith(prefix)]:
            del self._objects[key]

    def mkdir(self, path: str) -> None:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        self._objects[full_path] = (b"", datetime.now(timezone.utc))

    def exists(self, path: str) -> bool:
        return self._full_path(path) in self._objects

    # --- Listing ---

    def list_all_keys(self, prefix: str) -> list[str]:
        full_prefix = self._full_path(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        return [
            self._strip_prefix(key)
            for key in self._objects
            if key.startswith(full_prefix) and not key.endswith("/")
        ]

    def list_all_objects(self, prefix: str) -> list[tuple[str, int, str]]:
        full_prefix = self._full_path(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        objects = []
        for key, (content, modified) in self._objects.items():
            if not key.startswith(full_prefix) or key.endswith("/"):
                continue
            if key.split("/")[-1] == ".keep":
                continue
            objects.append((key, len(content), modified.isoformat()))
        return objects

    def list_(self, prefix: str) -> list[FileListItem]:
        full_prefix = self._full_path(prefix)
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        folder_names: dict[str, bool] = {}
        results: list[FileListItem] = []

        for key, (content, modified) in self._objects.items():
            if not key.startswith(full_prefix) or key == full_prefix:
                continue

            relative = key[len(full_prefix) :]

            if "/" in relative:
                folder_name = relative.split("/", 1)[0]
                remainder = relative.split("/", 1)[1]
                has_real_content = remainder != ""
                folder_names[folder_name] = (
                    folder_names.get(folder_name, False) or has_real_content
                )
                continue

            results.append(
                FileListItem(
                    id=None,
                    name=relative,
                    type="file",
                    size=len(content),
                    modified=modified.isoformat(),
                    is_empty=False,
                )
            )

        for folder_name, has_content in folder_names.items():
            results.append(
                FileListItem(
                    id=None,
                    name=folder_name,
                    type="folder",
                    size=0,
                    modified=None,
                    is_empty=not has_content,
                )
            )

        return results

    def info(self, path: str) -> FileInfo | FolderInfo:
        clean_path = path.rstrip("/")
        full_path = self._full_path(clean_path)
        name = clean_path.split("/")[-1]

        if full_path in self._objects:
            content, modified = self._objects[full_path]
            content_type, _ = mimetypes.guess_type(name)
            return FileInfo(
                id=None,
                name=name,
                path=clean_path,
                size=len(content),
                content_type=content_type or "application/octet-stream",
                modified=modified.isoformat(),
            )

        folder_key = full_path + "/"
        if folder_key in self._objects:
            _, modified = self._objects[folder_key]
            return FolderInfo(
                id=None,
                name=name,
                path=clean_path + "/",
                modified=modified.isoformat(),
            )

        for key, (_, modified) in self._objects.items():
            if key.startswith(folder_key):
                return FolderInfo(
                    id=None,
                    name=name,
                    path=clean_path + "/",
                    modified=modified.isoformat(),
                )

        raise FileNotFoundError(f"File does not exist: {path}")

    def list_tree(
        self, prefix: str, max_depth: int | None = None, max_entries: int = 50_000
    ) -> tuple[TreeNode, bool]:
        full_prefix = self._full_path(prefix)
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        root_rel = self._strip_prefix(full_prefix).rstrip("/")
        root_name = root_rel.split("/")[-1] if root_rel else ""
        nodes_by_path: dict[str, dict] = {
            full_prefix: {
                "name": root_name,
                "path": full_prefix,
                "type": "folder",
                "size": 0,
                "modified": None,
                "children_map": {},
            }
        }
        truncated = False
        count = 0

        for key, (content, modified) in self._objects.items():
            if not key.startswith(full_prefix) or key == full_prefix:
                continue
            if truncated:
                break

            rel = key[len(full_prefix) :]
            parts = rel.rstrip("/").split("/") if rel.rstrip("/") else []
            depth = len(parts)

            is_folder_marker = key.endswith("/")
            if max_depth is not None and depth > max_depth:
                parts = parts[:max_depth]
                depth = max_depth
                is_folder_marker = True
                obj_size = 0
                obj_modified = None
            else:
                obj_size = len(content)
                obj_modified = modified.isoformat()

            cur_path = full_prefix
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

            leaf_path = cur_path + leaf_name + ("/" if is_folder_marker else "")
            if leaf_path in nodes_by_path:
                continue

            if count >= max_entries:
                truncated = True
                break

            if is_folder_marker:
                node = {
                    "name": leaf_name,
                    "path": leaf_path,
                    "type": "folder",
                    "size": 0,
                    "modified": None,
                    "children_map": {},
                }
            else:
                node = {
                    "name": leaf_name,
                    "path": leaf_path,
                    "type": "file",
                    "size": obj_size,
                    "modified": obj_modified,
                    "children_map": None,
                }

            nodes_by_path[leaf_path] = node
            parent["children_map"][leaf_name] = node
            count += 1

        def build(node_dict) -> TreeNode:
            children = (
                None
                if node_dict["children_map"] is None
                else [build(child) for child in node_dict["children_map"].values()]
            )
            return TreeNode(
                id=None,
                name=node_dict["name"],
                path=node_dict["path"],
                type=node_dict["type"],
                size=node_dict["size"],
                modified=node_dict["modified"],
                children=children,
            )

        return build(nodes_by_path[full_prefix]), truncated

    # --- Move / rename / copy ---

    def _copy_into(
        self, source_path: str, destination_path: str
    ) -> tuple[str, list[str]]:
        """
        Copy source into the destination folder, deduping the destination name
        against existing keys.

        Returns (actual_destination_base, created_keys): for a file, both the
        exact target key; for a folder, the deduped folder base (ending in
        "/") and every key (including markers) created underneath it.
        """
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        # Single file
        if full_source in self._objects:
            source_name = full_source.rstrip("/").split("/")[-1]
            target_key = full_destination.rstrip("/") + "/" + source_name
            target_key = self._unique_key(target_key)
            self._objects[target_key] = self._objects[full_source]
            return target_key, [target_key]

        # Folder
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        source_folder_name = full_source.rstrip("/").split("/")[-1]
        dest_base = full_destination.rstrip("/") + "/" + source_folder_name
        dest_base = self._unique_key(dest_base, is_folder=True)

        created_keys = []
        for key in [k for k in self._objects if k.startswith(source_prefix)]:
            relative = key[len(source_prefix) :]
            destination_key = (
                dest_base + "/" + relative if relative else dest_base + "/"
            )
            self._objects[destination_key] = self._objects[key]
            created_keys.append(destination_key)

        if not created_keys:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        return dest_base + "/", created_keys

    def copy(self, source_path: str, destination_path: str) -> list[str]:
        return self._copy_into(source_path, destination_path)[1]

    def move(self, source_path: str, destination_path: str) -> str:
        actual_base, _ = self._copy_into(source_path, destination_path)
        self.delete(source_path)
        return actual_base

    def rename(self, source_path: str, destination_path: str) -> None:
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        if full_source.rstrip("/") == full_destination.rstrip("/"):
            raise ValueError("Source and destination are the same path.")

        if self._key_exists(full_destination, is_folder=False) or self._key_exists(
            full_destination, is_folder=True
        ):
            raise FileExistsError(f"Destination already exists: {destination_path}")

        # Single file
        if full_source in self._objects:
            self._objects[full_destination] = self._objects.pop(full_source)
            return

        # Folder: map source_prefix/* -> destination_prefix/* (no extra nesting)
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        dest_prefix = (
            full_destination
            if full_destination.endswith("/")
            else full_destination + "/"
        )

        keys_to_move = [k for k in self._objects if k.startswith(source_prefix)]
        if not keys_to_move:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        for key in keys_to_move:
            relative = key[len(source_prefix) :]
            self._objects[dest_prefix + relative] = self._objects.pop(key)

    # --- Archives ---

    def download_zip(self, paths: list[str]) -> Iterator[bytes]:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                if path.endswith("/"):
                    for key in self.list_all_keys(path):
                        file_bytes = self.download(key)
                        archive.writestr(key.lstrip("/"), file_bytes)
                else:
                    file_bytes = self.download(path)
                    archive.writestr(path.lstrip("/"), file_bytes)
        buffer.seek(0)
        yield buffer.read()

    def upload_archive(self, prefix: str, archive_file, archive_name: str) -> list[str]:
        self._check_archive_password(archive_file, archive_name)

        stem = archive_name
        for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".zip", ".tar"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break

        folder_key = prefix.rstrip("/") + "/" + stem
        full_folder_key = self._full_path(folder_key)
        unique_full_key = self._unique_key(full_folder_key, is_folder=True)
        unique_folder_path = self._strip_prefix(unique_full_key)

        extracted_paths = []

        for relative_path, file_bytes in self._iter_archive_entries(archive_file):
            destination_path = unique_folder_path.rstrip("/") + "/" + relative_path
            self.upload(destination_path, io.BytesIO(file_bytes))
            extracted_paths.append(destination_path)

        return extracted_paths
