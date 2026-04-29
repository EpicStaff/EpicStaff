import io
import zipfile
from typing import Iterator

import boto3
from botocore.exceptions import ClientError

from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.dataclasses import (
    FileInfo,
    FolderInfo,
    FileListItem,
    TreeNode,
    UploadResult,
)


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
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _full_path(self, path: str) -> str:
        """Prepend the organization prefix to a caller-provided path."""
        return self.organization_prefix + path.lstrip("/")

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
                real_files = [
                    obj for obj in probe.get("Contents", []) if obj["Key"] != folder_key
                ]
                is_empty = (
                    len(real_files) == 0 and len(probe.get("CommonPrefixes", [])) == 0
                )
                results.append(
                    FileListItem(
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
        return UploadResult(path=path, size=head["ContentLength"])

    def download(self, path: str) -> bytes:
        full_path = self._full_path(path)
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=full_path)
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File does not exist: {path}")
            raise
        return response["Body"].read()

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)

        # Attempt single-object delete first
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=full_path)
            self.client.delete_object(Bucket=self.bucket_name, Key=full_path)
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

    def mkdir(self, path: str) -> None:
        full_path = self._full_path(path)
        if not full_path.endswith("/"):
            full_path += "/"
        try:
            self.client.put_object(Bucket=self.bucket_name, Key=full_path, Body=b"")
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}")
            raise

    def move(self, source_path: str, destination_path: str) -> None:
        self.copy(source_path, destination_path)
        self.delete(source_path)

    def rename(self, source_path: str, destination_path: str) -> None:
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        if full_source.rstrip("/") == full_destination.rstrip("/"):
            raise ValueError("Source and destination are the same path.")

        # Single file
        if self.exists(source_path):
            self.client.copy_object(
                CopySource={"Bucket": self.bucket_name, "Key": full_source},
                Bucket=self.bucket_name,
                Key=full_destination,
            )
            self.client.delete_object(Bucket=self.bucket_name, Key=full_source)
            return

        # Folder: map source_prefix/* -> destination_prefix/* (no extra nesting)
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        dest_prefix = (
            full_destination
            if full_destination.endswith("/")
            else full_destination + "/"
        )

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

        self.client.delete_objects(
            Bucket=self.bucket_name, Delete={"Objects": keys_to_delete}
        )

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

    def copy(self, source_path: str, destination_path: str) -> list[str]:
        full_source = self._full_path(source_path)
        full_destination = self._full_path(destination_path)

        copy_source = {"Bucket": self.bucket_name, "Key": full_source}

        # Single file
        if self.exists(source_path):
            source_name = full_source.rstrip("/").split("/")[-1]
            target_key = full_destination.rstrip("/") + "/" + source_name
            target_key = self._unique_key(target_key)
            self.client.copy_object(
                CopySource=copy_source,
                Bucket=self.bucket_name,
                Key=target_key,
            )
            return [target_key]

        # Folder
        source_prefix = full_source if full_source.endswith("/") else full_source + "/"
        source_folder_name = full_source.rstrip("/").split("/")[-1]
        dest_base = full_destination.rstrip("/") + "/" + source_folder_name
        dest_base = self._unique_key(dest_base, is_folder=True)

        created_keys = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=source_prefix):
            for obj in page.get("Contents", []):
                relative = obj["Key"][len(source_prefix) :]
                destination_key = dest_base + "/" + relative
                self.client.copy_object(
                    CopySource={"Bucket": self.bucket_name, "Key": obj["Key"]},
                    Bucket=self.bucket_name,
                    Key=destination_key,
                )
                created_keys.append(destination_key)

        if not created_keys:
            raise FileNotFoundError(f"Source path does not exist: {source_path}")

        return created_keys

    def info(self, path: str) -> FileInfo | FolderInfo:
        clean_path = path.rstrip("/")
        full_path = self._full_path(clean_path)
        name = clean_path.split("/")[-1]

        # Try as file first
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=full_path)
            return FileInfo(
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
                raise ValueError(f"Invalid storage path: {path!r}")
            else:
                raise

        # Try as folder marker
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=full_path + "/")
            return FolderInfo(
                name=name,
                path=clean_path + "/",
                modified=head["LastModified"].isoformat(),
            )
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "404":
                pass
            elif code in ("400", "XMinioInvalidObjectName"):
                raise ValueError(f"Invalid storage path: {path!r}")
            else:
                raise

        # Fallback: virtual folder (no marker, but objects exist under prefix)
        prefix = full_path if full_path.endswith("/") else full_path + "/"
        response = self.client.list_objects_v2(
            Bucket=self.bucket_name, Prefix=prefix, MaxKeys=1
        )
        if response.get("Contents"):
            obj = response["Contents"][0]
            return FolderInfo(
                name=name,
                path=clean_path + "/",
                modified=obj["LastModified"].isoformat(),
            )
        raise FileNotFoundError(f"File does not exist: {path}")

    def exists(self, path: str) -> bool:
        full_path = self._full_path(path)
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=full_path)
            return True
        except ClientError as error:
            if error.response["Error"]["Code"] == "404":
                return False
            raise

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
                    archive_name = path.lstrip("/")
                    archive.writestr(archive_name, file_bytes)
        buffer.seek(0)
        yield buffer.read()

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
                name=node_dict["name"],
                path=node_dict["path"],
                type=node_dict["type"],
                size=node_dict["size"],
                modified=node_dict["modified"],
                children=children,
            )

        return build(nodes_by_path[full_prefix]), truncated

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
