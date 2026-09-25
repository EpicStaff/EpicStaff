import asyncio

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from tables.exceptions import RangeNotSatisfiable
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FileListItem,
    FolderInfo,
    TreeNode,
    UploadResult,
)
from tables.services.storage_service.path_utils import sanitize_storage_path
from utils.logger import logger

# For head_file: its caller (the shared pub/sub listener thread) must not stall for
# minutes on a slow or unreachable MinIO, so one short attempt and no retries.
_HEAD_FILE_CONFIG = Config(
    connect_timeout=2, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 1}
)

# S3 DeleteObjects accepts at most this many keys per request.
_DELETE_OBJECTS_BATCH = 1000


def _drop_expect_on_empty_body(request, **kwargs):
    # MinIO answers an empty PUT sent with "Expect: 100-continue" in a way that
    # stalls the next request on that pooled connection for ~30 s.
    if request.headers.get("Content-Length") == "0":
        request.headers.pop("Expect", None)


class S3StorageBackend(AbstractStorageBackend):
    """
    Storage backend for S3-compatible services (MinIO, AWS S3, etc.).

    Pass endpoint_url for MinIO or any non-AWS S3-compatible service.
    Leave endpoint_url as None to connect to AWS S3 directly.
    """

    def __init__(
        self,
        bucket_name: str,
        access_key: str,
        secret_key: str,
        organization_prefix: str = "org_1/",
        endpoint_url: str | None = None,
    ):
        self.bucket_name = bucket_name
        self.organization_prefix = organization_prefix

        def make_client(config: Config):
            return boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=config,
            )

        self.client = make_client(
            Config(
                connect_timeout=10,
                read_timeout=300,
                # Every upload slot may run a full archive PUT pool plus one streamed member.
                max_pool_connections=settings.UPLOAD_MAX_CONCURRENCY
                * (settings.ARCHIVE_UPLOAD_CONCURRENCY + 1),
            )
        )
        self.client.meta.events.register("before-send.s3.PutObject", _drop_expect_on_empty_body)
        self._head_file_client = make_client(_HEAD_FILE_CONFIG)

    async def upload_chunks(
        self, path, chunks, *, part_size, size_guard=None, before_commit=None
    ) -> int:
        """Upload an async stream of byte chunks to `path` as S3 multipart parts;
        returns the byte count.

        Holds one part in RAM (handed to boto as is, not copied). A body smaller than one part goes up as a single
        PutObject. size_guard(total) is called as bytes arrive and raises to stop.
        `await before_commit(total)` runs once every byte is in MinIO but before
        the object becomes visible: if it raises, the upload is aborted and an
        object already at `path` stays untouched."""
        full_key = self._full_path(path)
        total = 0
        buffer = bytearray()
        upload_id: str | None = None
        parts: list[dict] = []

        async def send_buffer_as_part() -> None:
            nonlocal upload_id, buffer
            if upload_id is None:
                mpu = await asyncio.to_thread(
                    self.client.create_multipart_upload, Bucket=self.bucket_name, Key=full_key
                )
                upload_id = mpu["UploadId"]
            number = len(parts) + 1
            body, buffer = buffer, bytearray()
            resp = await asyncio.to_thread(
                self.client.upload_part,
                Bucket=self.bucket_name,
                Key=full_key,
                UploadId=upload_id,
                PartNumber=number,
                Body=body,
            )
            parts.append({"ETag": resp["ETag"], "PartNumber": number})

        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if size_guard is not None:
                    size_guard(total)
                view = memoryview(chunk)
                while view:
                    room = part_size - len(buffer)
                    buffer += view[:room]
                    view = view[room:]
                    if len(buffer) == part_size:
                        await send_buffer_as_part()

            if upload_id is None:
                if before_commit is not None:
                    await before_commit(total)
                await asyncio.to_thread(self.put_bytes, path, buffer)
                return total

            if buffer:
                await send_buffer_as_part()
            if before_commit is not None:
                await before_commit(total)
            await asyncio.to_thread(
                self.client.complete_multipart_upload,
                Bucket=self.bucket_name,
                Key=full_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except BaseException:
            if upload_id is not None:
                await asyncio.to_thread(
                    self.client.abort_multipart_upload,
                    Bucket=self.bucket_name,
                    Key=full_key,
                    UploadId=upload_id,
                )
            raise
        return total

    def upload_stream(self, path: str, file_object, *, part_size: int) -> None:
        """Upload a readable of unknown size as multipart parts of `part_size`, one
        at a time on this thread, so it holds about one part in RAM; upload()
        uses boto's defaults (8 MB chunks on up to 10 threads)."""
        config = TransferConfig(
            multipart_threshold=part_size,
            multipart_chunksize=part_size,
            max_concurrency=1,
            use_threads=False,
        )
        self.client.upload_fileobj(
            file_object, self.bucket_name, self._full_path(path), Config=config
        )

    def put_bytes(self, path: str, data: bytes) -> int:
        """Store `data` at `path` in one PutObject; returns its size. Unlike upload()
        it skips the extra head_object request."""
        self.client.put_object(Bucket=self.bucket_name, Key=self._full_path(path), Body=data)
        return len(data)

    def _full_path(self, path: str) -> str:
        """Prepend the organization prefix to a caller-provided path."""
        safe_path = sanitize_storage_path(path, allow_empty=True)
        return self.organization_prefix + safe_path

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the organization prefix from an S3 key."""
        if full_key.startswith(self.organization_prefix):
            return full_key[len(self.organization_prefix) :]
        return full_key

    def list_all_keys(self, prefix: str) -> list[str]:
        full_prefix = self._full_path(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        paginator = self.client.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue
                keys.append(self._strip_prefix(obj["Key"]))
        return keys

    def list_all_objects(self, prefix: str) -> list[tuple[str, int, str]]:
        full_prefix = self._full_path(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        paginator = self.client.get_paginator("list_objects_v2")
        objects = []
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                if key.split("/")[-1] == ".keep":
                    continue
                objects.append((key, obj["Size"], obj["LastModified"].isoformat()))
        return objects

    def list_(self, prefix: str) -> list[FileListItem]:
        full_prefix = self._full_path(prefix)
        if full_prefix and not full_prefix.endswith("/"):
            full_prefix += "/"

        paginator = self.client.get_paginator("list_objects_v2")
        results: list[FileListItem] = []

        for page in paginator.paginate(
            Bucket=self.bucket_name,
            Prefix=full_prefix,
            Delimiter="/",
        ):
            for common_prefix in page.get("CommonPrefixes", []):
                folder_key = common_prefix["Prefix"]
                folder_name = folder_key.rstrip("/").split("/")[-1]
                probe = self.client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=folder_key,
                    Delimiter="/",
                    MaxKeys=2,
                )
                # folder_key itself is the zero-byte marker created by mkdir — exclude it
                real_files = [obj for obj in probe.get("Contents", []) if obj["Key"] != folder_key]
                is_empty = len(real_files) == 0 and len(probe.get("CommonPrefixes", [])) == 0
                results.append(
                    FileListItem(
                        id=None,
                        name=folder_name,
                        type="folder",
                        size=0,
                        modified=None,
                        is_empty=is_empty,
                    )
                )

            for obj in page.get("Contents", []):
                if obj["Key"] == full_prefix:
                    continue
                file_name = obj["Key"].split("/")[-1]
                results.append(
                    FileListItem(
                        id=None,
                        name=file_name,
                        type="file",
                        size=obj["Size"],
                        modified=obj["LastModified"].isoformat(),
                        is_empty=False,
                    )
                )

        return results

    def upload(self, path: str, file_object) -> UploadResult:
        full_path = self._full_path(path)
        self.client.upload_fileobj(file_object, self.bucket_name, full_path)
        head = self.client.head_object(Bucket=self.bucket_name, Key=full_path)
        logger.info("Uploaded S3 object {}", full_path)
        return UploadResult(path=path, size=head["ContentLength"])

    def download_range(self, path: str, first: int, last: int | None) -> tuple[bytes, str]:
        full_path = self._full_path(path)
        byte_range = f"bytes={first}-{'' if last is None else last}"
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name, Key=full_path, Range=byte_range
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "NoSuchKey":
                raise FileNotFoundError(f"File does not exist: {path}") from error
            if code == "InvalidRange":
                head = self.client.head_object(Bucket=self.bucket_name, Key=full_path)
                raise RangeNotSatisfiable(head["ContentLength"]) from error
            raise
        return response["Body"].read(), response["ContentRange"]

    def download(self, path: str) -> bytes:
        full_path = self._full_path(path)
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=full_path)
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File does not exist: {path}") from error
            raise
        return response["Body"].read()

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)

        # Attempt single-object delete first
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=full_path)
            self.client.delete_object(Bucket=self.bucket_name, Key=full_path)
            logger.info("Deleted S3 object {}", full_path)
            return
        except ClientError as error:
            if error.response["Error"]["Code"] != "404":
                raise

        # Treat as folder: delete all objects under the prefix
        prefix = full_path if full_path.endswith("/") else full_path + "/"
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": objects},
                )
                logger.info("Deleted {} S3 objects under prefix {}", len(objects), prefix)

    def delete_keys(self, keys: list[str]) -> None:
        for start in range(0, len(keys), _DELETE_OBJECTS_BATCH):
            batch = keys[start : start + _DELETE_OBJECTS_BATCH]
            response = self.client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            # DeleteObjects answers 200 even when single keys fail; they are listed here.
            if errors := response.get("Errors"):
                raise RuntimeError(
                    f"Could not delete {len(errors)} S3 objects, first {errors[0].get('Key')!r}: "
                    f"{errors[0].get('Code')}"
                )
        logger.info("Deleted {} S3 objects", len(keys))

    def _delete_created_keys(self, keys: list[str]) -> None:
        """Best-effort cleanup after a failed copy: a failure is only logged, so the
        caller re-raises the error that made the copy fail."""
        try:
            self.delete_keys(keys)
        except Exception:
            logger.exception("Could not remove {} objects of a failed copy", len(keys))

    def mkdir(self, path: str) -> None:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        try:
            self.client.put_object(Bucket=self.bucket_name, Key=full_path, Body=b"")
            logger.info("Created S3 folder {}", full_path)
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}") from error
            raise

    def claim_folder(self, path: str) -> bool:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        try:
            # Conditional write: MinIO/S3 refuse it when the marker already exists.
            self.client.put_object(
                Bucket=self.bucket_name, Key=full_path, Body=b"", IfNoneMatch="*"
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            # 412: the marker exists; 409: a concurrent conditional write is in flight;
            # XMinioParentIsObject: a file of that name appeared since unique_key.
            if code in (
                "PreconditionFailed",
                "412",
                "ConditionalRequestConflict",
                "409",
                "XMinioParentIsObject",
            ):
                return False
            if code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}") from error
            raise
        logger.info("Claimed S3 folder {}", full_path)
        return True

    def move(self, source_path: str, destination_path: str) -> str:
        actual_base, _ = self._copy_into(source_path, destination_path)
        self.delete(source_path)
        logger.info("Moved S3 path {} to {}", source_path, destination_path)
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
        if self.exists(source_path):
            self.client.copy_object(
                CopySource={"Bucket": self.bucket_name, "Key": full_source},
                Bucket=self.bucket_name,
                Key=full_destination,
            )
            self.client.delete_object(Bucket=self.bucket_name, Key=full_source)
            logger.info("Renamed S3 object {} to {}", full_source, full_destination)
            return

        # Folder: map source_prefix/* -> destination_prefix/* (no extra nesting)
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        dest_prefix = full_destination if full_destination.endswith("/") else full_destination + "/"

        paginator = self.client.get_paginator("list_objects_v2")
        keys_to_delete = []
        found = False
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=source_prefix):
            for obj in page.get("Contents", []):
                relative = obj["Key"][len(source_prefix) :]
                dest_key = dest_prefix + relative
                self.client.copy_object(
                    CopySource={"Bucket": self.bucket_name, "Key": obj["Key"]},
                    Bucket=self.bucket_name,
                    Key=dest_key,
                )
                keys_to_delete.append({"Key": obj["Key"]})
                found = True

        if not found:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        self.client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": keys_to_delete})
        logger.info("Renamed S3 prefix {} to {}", source_prefix, dest_prefix)

    def _key_exists(self, key: str, is_folder: bool) -> bool:
        if is_folder:
            probe = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=key if key.endswith("/") else key + "/",
                MaxKeys=1,
            )
            return probe.get("KeyCount", 0) > 0
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def _name_taken(self, key: str, is_folder: bool) -> bool:
        """A folder name is also taken by a file of that name: MinIO refuses to write
        under a path whose parent is an object (XMinioParentIsObject)."""
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

    def _copy_into(
        self, source_path: str, destination_path: str
    ) -> tuple[str, list[tuple[str, int]]]:
        """
        Copy source into the destination folder, deduping the destination name
        against existing keys.

        Returns (actual_destination_base, created): for a file, the exact target
        key and [(target_key, size)]; for a folder, the deduped folder base (ending
        in "/") and (key, size) of every object created underneath it. Sizes come
        from the source objects. If a copy fails midway, the objects already
        created are deleted again before the error propagates.
        """
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        copy_source = {"Bucket": self.bucket_name, "Key": full_source}

        # Single file
        source_size = self._object_size(source_path)
        if source_size is not None:
            source_name = full_source.rstrip("/").split("/")[-1]
            target_key = full_destination.rstrip("/") + "/" + source_name
            target_key = self.unique_key(target_key)
            self.client.copy_object(
                CopySource=copy_source,
                Bucket=self.bucket_name,
                Key=target_key,
            )
            return target_key, [(target_key, source_size)]

        # Folder
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        source_folder_name = full_source.rstrip("/").split("/")[-1]
        dest_base = full_destination.rstrip("/") + "/" + source_folder_name
        dest_base = self.unique_key(dest_base, is_folder=True)

        created: list[tuple[str, int]] = []
        paginator = self.client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=source_prefix):
                for obj in page.get("Contents", []):
                    relative = obj["Key"][len(source_prefix) :]
                    destination_key = dest_base + "/" + relative
                    self.client.copy_object(
                        CopySource={"Bucket": self.bucket_name, "Key": obj["Key"]},
                        Bucket=self.bucket_name,
                        Key=destination_key,
                    )
                    created.append((destination_key, obj["Size"]))
        except BaseException:
            if created:
                self._delete_created_keys([key for key, _ in created])
            raise

        if not created:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        return dest_base + "/", created

    def copy(self, source_path: str, destination_path: str) -> list[tuple[str, int]]:
        return self._copy_into(source_path, destination_path)[1]

    def info(self, path: str) -> FileInfo | FolderInfo:
        clean_path = path.rstrip("/")
        full_path = self._full_path(clean_path)
        name = clean_path.split("/")[-1]

        # Try as file first
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=full_path)
            return FileInfo(
                id=None,
                name=name,
                path=clean_path,
                size=head["ContentLength"],
                content_type=head.get("ContentType", "application/octet-stream"),
                modified=head["LastModified"].isoformat(),
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "404":
                pass
            elif code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}") from error
            else:
                raise

        # Try as folder marker
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=full_path + "/")
            return FolderInfo(
                id=None,
                name=name,
                path=clean_path + "/",
                modified=head["LastModified"].isoformat(),
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "404":
                pass
            elif code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}") from error
            else:
                raise

        # Fallback: virtual folder (no marker, but objects exist under prefix)
        prefix = full_path if full_path.endswith("/") else full_path + "/"
        response = self.client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix, MaxKeys=1)
        if response.get("Contents"):
            obj = response["Contents"][0]
            return FolderInfo(
                id=None,
                name=name,
                path=clean_path + "/",
                modified=obj["LastModified"].isoformat(),
            )
        raise FileNotFoundError(f"File does not exist: {path}")

    def head_file(self, path: str) -> FileInfo | None:
        clean_path = path.rstrip("/")
        try:
            head = self._head_file_client.head_object(
                Bucket=self.bucket_name, Key=self._full_path(clean_path)
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "404":
                return None
            if code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}") from error
            raise
        return FileInfo(
            id=None,
            name=clean_path.split("/")[-1],
            path=clean_path,
            size=head["ContentLength"],
            content_type=head.get("ContentType", "application/octet-stream"),
            modified=head["LastModified"].isoformat(),
        )

    def exists(self, path: str) -> bool:
        return self._object_size(path) is not None

    def _object_size(self, path: str) -> int | None:
        """Size of the object at path (a trailing "/" means the folder marker);
        None when there is none."""
        full_path = self._full_path(path)
        if path.endswith("/") and not full_path.endswith("/"):
            full_path += "/"
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=full_path)
        except ClientError as error:
            if error.response["Error"]["Code"] == "404":
                return None
            raise
        return head["ContentLength"]

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

        paginator = self.client.get_paginator("list_objects_v2")
        outer = False

        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=full_prefix):
            if outer:
                break

            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == full_prefix:
                    continue

                rel = key[len(full_prefix) :]
                parts = rel.rstrip("/").split("/") if rel.rstrip("/") else []
                depth = len(parts)

                is_folder_marker = key.endswith("/")
                if max_depth is not None and depth > max_depth:
                    # Truncate to max_depth and treat as synthetic folder at the cut
                    parts = parts[:max_depth]
                    depth = max_depth
                    is_folder_marker = True
                    obj_size = 0
                    obj_modified = None
                else:
                    obj_size = obj["Size"]
                    obj_modified = obj["LastModified"].isoformat()
                cur_path = full_prefix
                parent = nodes_by_path[cur_path]

                for segment in parts[:-1]:
                    cur_path = cur_path + segment + "/"
                    if cur_path not in nodes_by_path:
                        if count >= max_entries:
                            truncated = True
                            outer = True
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

                if outer:
                    break

                leaf_name = parts[-1] if parts else ""
                if not leaf_name:
                    continue

                leaf_path = cur_path + leaf_name + ("/" if is_folder_marker else "")
                if leaf_path in nodes_by_path:
                    continue

                if count >= max_entries:
                    truncated = True
                    outer = True
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
