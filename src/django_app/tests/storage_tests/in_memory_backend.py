import io
import mimetypes
import threading
import zipfile
from datetime import datetime, timezone

from botocore.exceptions import ClientError
from tables.exceptions import RangeNotSatisfiable
from tables.services.storage_service.base import AbstractStorageBackend, StorageUnreachable
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FolderInfo,
    FileListItem,
    TreeNode,
)
from tables.services.storage_service.path_utils import sanitize_storage_path, storage_key
from tables.services.storage_service.quota_service import record_files_within_quota
from tables.services.storage_service.s3_backend import S3StorageBackend

MODIFIED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class InMemoryStorageBackend(AbstractStorageBackend):
    """
    In-memory fake standing in for S3StorageBackend in tests.

    Mirrors S3 key semantics: everything is a flat dict of full key -> (bytes,
    modified datetime). Folders have no real existence — they are either a
    zero-byte marker key ending in "/" (created by mkdir) or implied by files
    living under a common prefix (a "virtual folder"). Like MinIO, it refuses to
    write a key under a path that is a stored object (XMinioParentIsObject).
    """

    def __init__(self, organization_prefix: str = "", part_size: int = 16 * 1024 * 1024):
        self.organization_prefix = organization_prefix
        self._part_size = part_size
        self._objects: dict[str, tuple[bytes, datetime]] = {}

    def _full_path(self, path: str) -> str:
        """Prepend the organization prefix to a caller-provided path."""
        safe_path = sanitize_storage_path(path, allow_empty=True)
        return self.organization_prefix + safe_path

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the organization prefix from a stored key."""
        if full_key.startswith(self.organization_prefix):
            return full_key[len(self.organization_prefix) :]
        return full_key

    def _parent_object(self, full_key: str) -> str | None:
        """The stored object that is an ancestor path of full_key, if any."""
        segments = full_key.rstrip("/").split("/")
        if full_key.endswith("/"):
            segments.append("")
        for depth in range(1, len(segments)):
            ancestor = "/".join(segments[:depth])
            if ancestor in self._objects:
                return ancestor
        return None

    def _store(self, full_key: str, entry: tuple[bytes, datetime]) -> None:
        if (parent := self._parent_object(full_key)) is not None:
            raise ClientError(
                {
                    "Error": {
                        "Code": "XMinioParentIsObject",
                        "Message": f"Object-prefix is already an object: {parent}",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 400},
                },
                "PutObject",
            )
        self._objects[full_key] = entry

    def _key_exists(self, key: str, is_folder: bool) -> bool:
        if is_folder:
            folder_prefix = key if key.endswith("/") else key + "/"
            if folder_prefix in self._objects:
                return True
            return any(k.startswith(folder_prefix) for k in self._objects)
        return key in self._objects

    def _name_taken(self, key: str, is_folder: bool) -> bool:
        if is_folder:
            return self._key_exists(key, is_folder=True) or self._key_exists(
                key.rstrip("/"), is_folder=False
            )
        return self._key_exists(key, is_folder=False)

    def unique_key(self, key: str, is_folder: bool = False) -> str:
        """Increment the name segment of *key* until nothing exists at that path."""
        if not self._name_taken(key, is_folder):
            return key
        parts = key.rstrip("/").rsplit("/", 1)
        parent = parts[0] + "/" if len(parts) > 1 else ""
        name = parts[-1]
        while True:
            name = self._increment_name(name, is_folder=is_folder)
            candidate = parent + name
            if not self._name_taken(candidate, is_folder):
                return candidate

    # --- Basic operations ---

    @property
    def part_size(self) -> int:
        return self._part_size

    async def upload_chunks(self, path: str, chunks, *, size_guard=None, before_commit=None) -> int:
        """Async twin of S3StorageBackend.upload_chunks; nothing is stored on abort."""
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            if size_guard is not None:
                size_guard(len(buffer))
        if before_commit is not None:
            await before_commit(len(buffer))
        return self.put_bytes(path, buffer)

    def upload_stream(self, path: str, file_object) -> None:
        self.put_bytes(path, file_object.read())

    def put_bytes(self, path: str, data: bytes) -> int:
        self._store(self._full_path(path), (bytes(data), datetime.now(timezone.utc)))
        return len(data)

    def download(self, path: str) -> bytes:
        full_path = self._full_path(path)
        if full_path not in self._objects:
            raise FileNotFoundError(f"File does not exist: {path}")
        return self._objects[full_path][0]

    def download_range(self, path: str, first: int, last: int | None) -> tuple[bytes, str]:
        data = self.download(path)
        if first >= len(data):
            raise RangeNotSatisfiable(len(data))
        last = len(data) - 1 if last is None else min(last, len(data) - 1)
        return data[first : last + 1], f"bytes {first}-{last}/{len(data)}"

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)
        if full_path in self._objects:
            del self._objects[full_path]
            return

        prefix = full_path if full_path.endswith("/") else full_path + "/"
        for key in [k for k in self._objects if k.startswith(prefix)]:
            del self._objects[key]

    def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self._objects.pop(key, None)

    def mkdir(self, path: str) -> None:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        self._store(full_path, (b"", datetime.now(timezone.utc)))

    def claim_folder(self, path: str) -> bool:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        # S3StorageBackend reports XMinioParentIsObject as a lost claim too.
        if full_path in self._objects or self._parent_object(full_path) is not None:
            return False
        self._objects[full_path] = (b"", datetime.now(timezone.utc))
        return True

    def exists(self, path: str) -> bool:
        full_path = self._full_path(path)
        if path.endswith("/") and not full_path.endswith("/"):
            full_path += "/"
        return full_path in self._objects

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

    def head_file(self, path: str) -> FileInfo | None:
        clean_path = path.rstrip("/")
        stored = self._objects.get(self._full_path(clean_path))
        if stored is None:
            return None
        content, modified = stored
        content_type, _ = mimetypes.guess_type(clean_path)
        return FileInfo(
            id=None,
            name=clean_path.split("/")[-1],
            path=clean_path,
            size=len(content),
            content_type=content_type or "application/octet-stream",
            modified=modified.isoformat(),
        )

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
    ) -> tuple[str, list[tuple[str, int]]]:
        """
        Copy source into the destination folder, deduping the destination name
        against existing keys.

        Returns (actual_destination_base, created): for a file, the exact target
        key and [(target_key, size)]; for a folder, the deduped folder base
        (ending in "/") and (key, size) of every object (markers included)
        created underneath it.
        """
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        # Single file
        if full_source in self._objects:
            source_name = full_source.rstrip("/").split("/")[-1]
            target_key = full_destination.rstrip("/") + "/" + source_name
            target_key = self.unique_key(target_key)
            self._store(target_key, self._objects[full_source])
            return target_key, [(target_key, len(self._objects[full_source][0]))]

        # Folder
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        source_folder_name = full_source.rstrip("/").split("/")[-1]
        dest_base = full_destination.rstrip("/") + "/" + source_folder_name
        dest_base = self.unique_key(dest_base, is_folder=True)

        created = []
        for key in [k for k in self._objects if k.startswith(source_prefix)]:
            relative = key[len(source_prefix) :]
            destination_key = (
                dest_base + "/" + relative if relative else dest_base + "/"
            )
            self._store(destination_key, self._objects[key])
            created.append((destination_key, len(self._objects[key][0])))

        if not created:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        return dest_base + "/", created

    def copy(self, source_path: str, destination_path: str) -> list[tuple[str, int]]:
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
            self._store(full_destination, self._objects[full_source])
            del self._objects[full_source]
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
            self._store(dest_prefix + relative, self._objects[key])
            del self._objects[key]


class FailingInMemoryBackend(InMemoryStorageBackend):
    """In-memory storage that is unreachable for every key ending in failing_key_suffix."""

    def __init__(self, failing_key_suffix: str, part_size: int = 16 * 1024 * 1024):
        super().__init__(part_size=part_size)
        self.failing_key_suffix = failing_key_suffix

    def put_bytes(self, path: str, data: bytes) -> int:
        if path.endswith(self.failing_key_suffix):
            raise StorageUnreachable("storage went away")
        return super().put_bytes(path, data)

    def upload_stream(self, path: str, file_object) -> None:
        if path.endswith(self.failing_key_suffix):
            raise StorageUnreachable("storage went away")
        super().upload_stream(path, file_object)


def client_error(code: str, status: int, operation: str = "PutObject") -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, operation
    )


class _Paginator:
    def __init__(self, client, page_size):
        self._client = client
        self._page_size = page_size

    def paginate(self, *, Bucket, Prefix):
        keys = sorted(key for key in self._client.objects if key.startswith(Prefix))
        for start in range(0, len(keys), self._page_size):
            yield {
                "Contents": [
                    {"Key": key, "Size": len(self._client.objects[key]), "LastModified": MODIFIED}
                    for key in keys[start : start + self._page_size]
                ]
            }


class FakeS3Client:
    """The slice of the boto3 S3 client that S3StorageBackend uses, over a dict."""

    def __init__(self, page_size=2):
        self.objects: dict[str, bytes] = {}
        self.page_size = page_size
        self.fail_copy_number: int | None = None  # 1-based copy_object call to fail
        self.copy_error: BaseException = client_error("InternalError", 500, "CopyObject")
        self.delete_error: BaseException | None = None
        self.delete_batches: list[list[str]] = []
        self.head_calls: list[str] = []
        self.puts: list[bytes] = []
        self.parts: dict[int, bytes] = {}
        self.completed: list[dict] | None = None
        self.aborted = False
        self.peak_live_parts = 0
        self._live_parts = 0
        self._copies = 0
        self._lock = threading.Lock()

    def head_object(self, *, Bucket, Key):
        self.head_calls.append(Key)
        if Key not in self.objects:
            raise client_error("404", 404, "HeadObject")
        return {
            "ContentLength": len(self.objects[Key]),
            "LastModified": MODIFIED,
            "ContentType": "text/plain",
        }

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys=1000, Delimiter=None):
        keys = sorted(key for key in self.objects if key.startswith(Prefix))[:MaxKeys]
        return {
            "KeyCount": len(keys),
            "Contents": [
                {"Key": key, "Size": len(self.objects[key]), "LastModified": MODIFIED}
                for key in keys
            ],
        }

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self, self.page_size)

    def copy_object(self, *, CopySource, Bucket, Key):
        self._copies += 1
        if self._copies == self.fail_copy_number:
            raise self.copy_error
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_objects(self, *, Bucket, Delete):
        keys = [entry["Key"] for entry in Delete["Objects"]]
        assert len(keys) <= 1000
        self.delete_batches.append(keys)
        if self.delete_error is not None:
            raise self.delete_error
        for key in keys:
            self.objects.pop(key, None)
        return {}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.puts.append(bytes(Body))
        self.objects[Key] = bytes(Body)

    def create_multipart_upload(self, *, Bucket, Key):
        return {"UploadId": "upload-1"}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        with self._lock:
            self._live_parts += 1
            self.peak_live_parts = max(self.peak_live_parts, self._live_parts)
        self.parts[PartNumber] = bytes(Body)
        with self._lock:
            self._live_parts -= 1
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        self.completed = MultipartUpload["Parts"]

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.aborted = True


def make_s3_backend(client: FakeS3Client, part_size: int = 16 * 1024 * 1024) -> S3StorageBackend:
    """S3StorageBackend talking to `client`, without building real boto3 clients."""
    backend = S3StorageBackend.__new__(S3StorageBackend)
    backend.bucket_name = "bucket"
    backend.organization_prefix = ""
    backend.client = client
    backend._head_file_client = client
    backend._part_size = part_size
    return backend


def seed_file(backend, org_id: int, path: str, content: bytes) -> None:
    """Store a file of the org and record its row within the quota, as a finished
    upload leaves it."""
    backend.put_bytes(storage_key(org_id, path), content)
    record_files_within_quota(org_id, [(path, len(content))])


async def async_chunks(*chunks: bytes):
    """A request body arriving as `chunks`."""
    for chunk in chunks:
        yield chunk


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()
