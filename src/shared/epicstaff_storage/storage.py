from __future__ import annotations

import json
import os
import posixpath
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class StoragePermissionError(PermissionError):
    """Raised when a storage operation is denied by the path allowlist."""

    pass


__cache: dict[str, list[str] | None] = {}

_mutations: list[dict] = []


def __get_allowed_paths() -> list[str] | None:
    if "allowed" not in __cache:
        raw = os.environ.get("STORAGE_ALLOWED_PATHS")
        __cache["allowed"] = json.loads(raw) if raw is not None else None
    return __cache["allowed"]


def __normalize_path(path: str) -> str:
    p = path.lstrip("/")
    p = posixpath.normpath(p)
    if p == ".":
        p = ""
    if p.startswith(".."):
        raise StoragePermissionError(f"Path traversal detected: '{path}'")
    return p


def __is_path_allowed(normalized_path: str, allowed_paths: list[str]) -> bool:
    for allowed in allowed_paths:
        allowed_norm = __normalize_path(allowed)
        if allowed.endswith("/"):
            folder_prefix = allowed_norm + "/"
            if normalized_path == allowed_norm or normalized_path.startswith(
                folder_prefix
            ):
                return True
        else:
            if normalized_path == allowed_norm:
                return True
    return False


def check_storage_permission(operation: str, path: str) -> None:
    allowed = __get_allowed_paths()
    if allowed is None:
        return
    normalized = __normalize_path(path)
    if not __is_path_allowed(normalized, allowed):
        raise StoragePermissionError(
            f"Access denied: {operation} on '{path}' — not in this flow's allowed files."
        )


def get_mutations() -> list[dict]:
    return list(_mutations)


def clear_mutations() -> None:
    _mutations.clear()


class EpicStaffStorage:
    def __init__(self) -> None:
        self._client: object | None = None
        self._bucket: str | None = None

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client

        required_vars = {
            "STORAGE_ENDPOINT": os.environ.get("STORAGE_ENDPOINT"),
            "STORAGE_ACCESS_KEY": os.environ.get("STORAGE_ACCESS_KEY"),
            "STORAGE_SECRET_KEY": os.environ.get("STORAGE_SECRET_KEY"),
            "STORAGE_BUCKET_NAME": os.environ.get("STORAGE_BUCKET_NAME"),
        }
        missing = [name for name, value in required_vars.items() if not value]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        import boto3  # type: ignore[import-untyped]

        self._client = boto3.client(
            "s3",
            endpoint_url=required_vars["STORAGE_ENDPOINT"],
            aws_access_key_id=required_vars["STORAGE_ACCESS_KEY"],
            aws_secret_access_key=required_vars["STORAGE_SECRET_KEY"],
        )
        self._bucket = required_vars["STORAGE_BUCKET_NAME"]
        return self._client

    def _normalize_key(self, path: str) -> str:
        relative = path.lstrip("/")
        prefix = os.environ.get("STORAGE_ORG_PREFIX") or None
        if prefix:
            return f"{prefix}/{relative}"
        return relative

    def _bucket_name(self) -> str:
        self._get_client()
        assert self._bucket is not None  # always set by _get_client
        return self._bucket

    def _handle_client_error(self, error: Exception, path: str) -> None:
        try:
            from botocore.exceptions import ClientError  # type: ignore[import-untyped]

            if isinstance(error, ClientError):
                code = error.response["Error"]["Code"]  # type: ignore[attr-defined]
                if code in ("NoSuchKey", "404"):
                    raise FileNotFoundError(f"Not found in storage: {path}") from error
        except ImportError:
            pass
        raise RuntimeError(f"Storage error for '{path}': {error}") from error

    def read(self, path: str) -> str:
        check_storage_permission("read", path)
        return self.read_bytes(path).decode("utf-8")

    def read_bytes(self, path: str) -> bytes:
        check_storage_permission("read_bytes", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            response = client.get_object(Bucket=self._bucket_name(), Key=key)  # type: ignore[attr-defined]
            return response["Body"].read()
        except Exception as error:
            self._handle_client_error(error, path)
            raise  # unreachable, satisfies type checker

    def write(self, path: str, content: str) -> None:
        check_storage_permission("write", path)
        self.write_bytes(path, content.encode("utf-8"))

    def write_bytes(self, path: str, content: bytes) -> None:
        check_storage_permission("write_bytes", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            client.put_object(Bucket=self._bucket_name(), Key=key, Body=content)  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

        _mutations.append({"op": "write", "path": key})

    def list(self, path: str) -> list[dict]:
        check_storage_permission("list", path)
        client = self._get_client()
        prefix = self._normalize_key(path)
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        try:
            response = client.list_objects_v2(  # type: ignore[attr-defined]
                Bucket=self._bucket_name(), Prefix=prefix, Delimiter="/"
            )
        except Exception as error:
            self._handle_client_error(error, path)
            raise  # unreachable, satisfies type checker

        entries: list[dict] = []

        for common_prefix in response.get("CommonPrefixes") or []:
            folder_key = common_prefix["Prefix"]
            folder_name = folder_key.rstrip("/").split("/")[-1]
            entries.append(
                {"name": folder_name, "type": "folder", "size": 0, "modified": None}
            )

        for obj in response.get("Contents") or []:
            object_key = obj["Key"]
            object_name = object_key.split("/")[-1]
            if object_name == ".keep":
                continue
            modified = obj.get("LastModified")
            entries.append(
                {
                    "name": object_name,
                    "type": "file",
                    "size": obj.get("Size", 0),
                    "modified": modified.isoformat() if modified else None,
                }
            )

        return entries

    def exists(self, path: str) -> bool:
        check_storage_permission("exists", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            client.head_object(Bucket=self._bucket_name(), Key=key)  # type: ignore[attr-defined]
            return True
        except Exception as error:
            try:
                from botocore.exceptions import ClientError  # type: ignore[import-untyped]

                if isinstance(error, ClientError):
                    code = error.response["Error"]["Code"]  # type: ignore[attr-defined]
                    if code in ("NoSuchKey", "404"):
                        prefix = key if key.endswith("/") else key + "/"
                        try:
                            response = client.list_objects_v2(  # type: ignore[attr-defined]
                                Bucket=self._bucket_name(), Prefix=prefix, MaxKeys=1
                            )
                            return bool(
                                response.get("Contents")
                                or response.get("CommonPrefixes")
                            )
                        except Exception:
                            return False
            except ImportError:
                pass
            raise RuntimeError(f"Storage error for '{path}': {error}") from error

    def delete(self, path: str) -> None:
        check_storage_permission("delete", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            client.delete_object(Bucket=self._bucket_name(), Key=key)  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

        _mutations.append({"op": "delete", "path": key})

    def mkdir(self, path: str) -> None:
        check_storage_permission("mkdir", path)
        client = self._get_client()
        normalized = self._normalize_key(path).rstrip("/")
        keep_key = normalized + "/.keep"
        try:
            client.put_object(Bucket=self._bucket_name(), Key=keep_key, Body=b"")  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

    def move(self, src: str, dst: str) -> None:
        check_storage_permission("move", src)
        check_storage_permission("move_dst", dst)
        self.copy(src, dst)
        self.delete(src)

    def copy(self, src: str, dst: str) -> None:
        check_storage_permission("copy", src)
        check_storage_permission("copy_dst", dst)
        client = self._get_client()
        src_key = self._normalize_key(src)
        dst_key = self._normalize_key(dst)
        bucket = self._bucket_name()
        try:
            client.copy_object(  # type: ignore[attr-defined]
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": src_key},
                Key=dst_key,
            )
        except Exception as error:
            self._handle_client_error(error, src)

        _mutations.append({"op": "write", "path": dst_key})

    def info(self, path: str) -> dict:
        check_storage_permission("info", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            response = client.head_object(Bucket=self._bucket_name(), Key=key)  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)
            raise  # unreachable, satisfies type checker

        modified = response.get("LastModified")
        return {
            "name": key.split("/")[-1],
            "size": response.get("ContentLength", 0),
            "content_type": response.get("ContentType", ""),
            "modified": modified.isoformat() if modified else None,
        }

    @contextmanager
    def as_local(self, path: str) -> Generator[str, None, None]:
        check_storage_permission("as_local", path)
        suffix = Path(self._normalize_key(path)).suffix
        content = self.read_bytes(path)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            yield tmp_path
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
