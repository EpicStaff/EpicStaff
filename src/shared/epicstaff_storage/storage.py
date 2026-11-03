from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from pathlib import Path

from .blocked_extensions import BLOCKED_EXTENSIONS
from .path_safety import sanitize_storage_path


class StoragePermissionError(PermissionError):
    """Raised when a storage operation is denied by the path allowlist."""


class StorageSizeLimitError(RuntimeError):
    pass


class StorageQuotaExceededError(RuntimeError):
    """Raised before a write that would not fit the organization's storage quota.

    A RuntimeError of its own rather than a StorageSizeLimitError: that one says a single
    file is too big to read, whereas this depends on how full the whole organization is,
    so code handling an oversized file must not catch it by accident.
    """


class StorageLineEditMismatchError(ValueError):
    pass


MAX_LINE_READ_BYTES = 50 * 1024 * 1024

# The org-root folder Django keeps deleted files in (a copy of django_app's
# path_utils.TRASH_DIRECTORY: this library can't import django_app). Runtime
# code never reads, writes or lists it, whatever its allowed paths say.
RESERVED_DIRECTORY = ".recycle-bin"

# Operation names passed to `check_storage_permission`, mapped to the actions they
# need on a path outside the run's own folders. Values are `StorageAction` values
# (a copy: this library can't import shared.models). Edit/append/insert have no entry
# of their own: they read first and then write, so they hit "read" and "write".
# A move needs READ on its source as well, because it copies before it deletes.
_REQUIRED_ACTIONS: dict[str, tuple[str, ...]] = {
    "read": ("read",),
    "read_bytes": ("read",),
    "list": ("read",),
    "walk": ("read",),
    "exists": ("read",),
    "info": ("read",),
    "as_local": ("read",),
    "copy": ("read",),
    "write": ("write",),
    "write_bytes": ("write",),
    "mkdir": ("write",),
    "copy_dst": ("write",),
    "move_dst": ("write",),
    "delete": ("delete",),
    "move": ("delete", "read"),
}

# Operations whose path is created or overwritten, so an executable name is refused.
_WRITE_TARGET_OPERATIONS = frozenset({"write", "write_bytes", "copy_dst", "move_dst"})

_MISSING_PERMISSION_HINTS = {
    "read": "reading files needs the Files: Read permission",
    "write": "writing files needs the Files: Create and Files: Update permissions",
    "delete": "deleting files needs the Files: Delete permission",
}


def split_lines(content: str) -> list[str]:
    """Split ``content`` into logical lines using wc-with-final-fragment
    semantics: a trailing ``"\\n"`` terminates the preceding line (no
    phantom empty line is produced after it), while content that does
    *not* end in ``"\\n"`` still counts its final, unterminated fragment
    as a line. An empty string has zero lines.

    This is the single source of truth for line counting/addressing:
    ``count_lines``, ``read_lines``, and ``insert_lines`` below, plus the
    ``s3_file_count_lines_tool`` / ``s3_file_insert_tool`` /
    ``s3_file_line_read_tool`` / ``s3_bash_tool`` (head/tail) callers, all
    rely on this so identical content yields identical line numbers
    everywhere.
    """
    if content == "":
        return []
    content = content.removesuffix("\n")
    return content.split("\n")


__cache: dict[str, list[str] | None] = {}

_mutations: list[dict] = []

# Bytes this process has added to storage, counted against STORAGE_FREE_BYTES.
_bytes_added = 0


def __get_allowed_paths() -> list[str] | None:
    if "allowed" not in __cache:
        raw = os.environ.get("STORAGE_ALLOWED_PATHS")
        __cache["allowed"] = json.loads(raw) if raw is not None else None
    return __cache["allowed"]


def __get_allowed_actions() -> list[str] | None:
    if "actions" not in __cache:
        raw = os.environ.get("STORAGE_ALLOWED_ACTIONS")
        __cache["actions"] = json.loads(raw) if raw is not None else None
    return __cache["actions"]


def __get_own_paths() -> list[str]:
    if "own" not in __cache:
        raw = os.environ.get("STORAGE_OWN_PATHS")
        __cache["own"] = json.loads(raw) if raw is not None else None
    return __cache["own"] or []


def _optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    return int(raw) if raw else None


def _format_size(size_bytes: int) -> str:
    """Human-readable size like the web UI shows: whole units, one decimal from MB up."""
    units = ["B", "KB", "MB", "GB", "TB"]
    if size_bytes <= 0:
        return "0 B"
    unit_index = 0
    value = float(size_bytes)
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    shown = f"{value:.1f}" if unit_index >= 2 else str(round(value))
    return f"{shown} {units[unit_index]}"


def _safe_relative_path(path: str) -> str:
    """Normalize a storage path and convert ValueError to StoragePermissionError.

    This is the only place where ValueError from sanitize_storage_path adapts
    to StoragePermissionError. All other call sites catch ValueError separately
    (e.g., delete_folder) to preserve their documented behavior.
    """
    try:
        return sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
    except ValueError as e:
        raise StoragePermissionError(str(e)) from e


def __is_path_allowed(normalized_path: str, allowed_paths: list[str]) -> bool:
    for allowed in allowed_paths:
        allowed_norm = _safe_relative_path(allowed)
        if allowed.endswith("/"):
            folder_prefix = allowed_norm + "/"
            if normalized_path == allowed_norm or normalized_path.startswith(folder_prefix):
                return True
        else:
            if normalized_path == allowed_norm:
                return True
    return False


_MAX_ALLOWED_PATHS_IN_MESSAGE = 15


def __format_allowed_paths(allowed: list[str]) -> str:
    shown = ", ".join(allowed[:_MAX_ALLOWED_PATHS_IN_MESSAGE])
    remainder = len(allowed) - _MAX_ALLOWED_PATHS_IN_MESSAGE
    if remainder > 0:
        shown += f" ({remainder} more)"
    return shown


def is_reserved_path(relative_path: str) -> bool:
    """True for the recycle-bin folder and anything under it (org-relative path)."""
    return relative_path.lstrip("/").split("/", 1)[0] == RESERVED_DIRECTORY


def __check_allowed_actions(operation: str, path: str, normalized_path: str) -> None:
    """Refuse an operation whose action the run's FILES permissions don't grant.

    Skipped when the issuer did not narrow the actions (env var absent) and for paths
    inside the run's own folders, where every action is allowed. An operation missing
    from `_REQUIRED_ACTIONS` is refused whenever the actions are narrowed.
    """
    allowed_actions = __get_allowed_actions()
    if allowed_actions is None:
        return
    # An operation without an entry would otherwise need no action and always pass, so
    # a new operation added without one fails closed instead of bypassing the narrowing.
    required_actions = _REQUIRED_ACTIONS.get(operation)
    if required_actions is None:
        raise StoragePermissionError(
            f"Access denied: {operation} on '{path}' has no permission mapping, so it "
            "is refused for this run."
        )
    if __is_path_allowed(normalized_path, __get_own_paths()):
        return
    for action in required_actions:
        if action not in allowed_actions:
            raise StoragePermissionError(
                f"Access denied: {operation} on '{path}' is not allowed for this run: "
                f"{_MISSING_PERMISSION_HINTS[action]}."
            )


def check_storage_permission(operation: str, path: str) -> None:
    normalized = _safe_relative_path(path)
    if is_reserved_path(normalized):
        raise StoragePermissionError(
            f"Access denied: '{RESERVED_DIRECTORY}' holds deleted files and is not available to flows."
        )
    allowed = __get_allowed_paths()
    if allowed is not None and not __is_path_allowed(normalized, allowed):
        if allowed:
            allowed_hint = (
                f" Allowed paths: [{__format_allowed_paths(allowed)}]. "
                "Specify one of these (root/'' listing is not available)."
            )
        else:
            allowed_hint = " This flow has no allowed files."
        raise StoragePermissionError(
            f"Access denied: {operation} on '{path}' is not within this flow's "
            f"allowed files.{allowed_hint}"
        )
    __check_allowed_actions(operation, path, normalized)
    if operation in _WRITE_TARGET_OPERATIONS:
        extension = os.path.splitext(normalized)[1].lower()
        if extension in BLOCKED_EXTENSIONS:
            raise StoragePermissionError(
                f"Access denied: {operation} on '{path}' is refused: files with the "
                f"'{extension}' extension are executable and cannot be stored."
            )


def _record_added_bytes(added_bytes: int) -> None:
    global _bytes_added
    _bytes_added += added_bytes


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
            raise OSError(f"Missing required environment variables: {', '.join(missing)}")

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
        relative = _safe_relative_path(path)
        # Preserve trailing slash if it was in the input
        if relative and path.endswith("/"):
            relative += "/"
        prefix = os.environ.get("STORAGE_ORG_PREFIX") or None
        if prefix:
            return f"{prefix}/{relative}"
        return relative

    def _strip_org_prefix(self, key: str) -> str:
        prefix = os.environ.get("STORAGE_ORG_PREFIX") or None
        if prefix and key.startswith(f"{prefix}/"):
            return key[len(prefix) + 1 :]
        return key

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
                if code in ("AccessDenied", "403"):
                    storage_operation = error.operation_name  # type: ignore[attr-defined]
                    raise StoragePermissionError(
                        f"Access denied: storage refused {storage_operation} on '{path}'. "
                        "The storage account of this run is not allowed to do this; "
                        "check the Files permissions of the user who started it."
                    ) from error
        except ImportError:
            pass
        raise RuntimeError(f"Storage error for '{path}': {error}") from error

    def _stored_size(self, key: str) -> int | None:
        """Size of the object at `key`, or None when there is none or storage cannot say."""
        try:
            response = self._get_client().head_object(  # type: ignore[attr-defined]
                Bucket=self._bucket_name(), Key=key
            )
        except Exception:
            return None
        return response.get("ContentLength", 0)

    def _admit_write(self, path: str, key: str, size_of_write: Callable[[], int | None]) -> int:
        """Decide whether a write fits the organization's quota; return the bytes it adds.

        Django hands the run `STORAGE_FREE_BYTES` and `STORAGE_PURGEABLE_BYTES` when it
        issues the credentials; without them nothing is checked. A write that fits the
        free bytes left, minus what this process already wrote, goes ahead. One that only
        fits once the oldest recycle-bin items are purged goes ahead after a warning on
        stderr, since django purges them when it learns of the write. One that does not fit even
        then is refused, with nothing written.

        The destination's current size is only looked up when the write would otherwise be
        warned about or refused, because overwriting frees those bytes: a write of content
        in hand pays no extra storage call, and counts the whole of its size. A copy has to
        look up its source to know its size. When that lookup fails the size is unknown:
        the copy is refused only if no free byte is left, otherwise it goes ahead, uncounted,
        and django's enforcement after the run catches what the library could not.

        Raises:
            StorageQuotaExceededError: the write does not fit even after purging the bin.
        """
        free_bytes = _optional_int_env("STORAGE_FREE_BYTES")
        if free_bytes is None:
            return 0
        purgeable_bytes = _optional_int_env("STORAGE_PURGEABLE_BYTES") or 0
        remaining_bytes = free_bytes - _bytes_added
        # Nothing can be added or purged: django issued the account without any write
        # access, so even an empty file would only fail later as a permission error.
        if free_bytes + purgeable_bytes <= 0:
            raise self._quota_error(path, 0, 0)
        size = size_of_write()
        if size is None:
            if remaining_bytes <= 0:
                raise self._quota_error(path, 0, max(0, purgeable_bytes + remaining_bytes))
            return 0
        if size == 0 or size <= remaining_bytes:
            return size
        added_bytes = max(0, size - (self._stored_size(key) or 0))
        if added_bytes <= remaining_bytes:
            return added_bytes
        if added_bytes <= remaining_bytes + purgeable_bytes:
            print(
                "This file may not fit in the remaining storage "
                f"({_format_size(remaining_bytes)} free); the oldest recycle-bin items may be "
                "permanently deleted to make room.",
                file=sys.stderr,
            )
            return added_bytes
        raise self._quota_error(path, added_bytes, max(0, remaining_bytes + purgeable_bytes))

    @staticmethod
    def _quota_error(
        path: str, needed_bytes: int, available_bytes: int
    ) -> StorageQuotaExceededError:
        if available_bytes == 0:
            return StorageQuotaExceededError(
                f"Organization storage quota reached: no storage is left, so '{path}' was not "
                "written. Delete files to free space."
            )
        return StorageQuotaExceededError(
            f"Organization storage quota reached: writing '{path}' needs "
            f"{_format_size(needed_bytes)} but only {_format_size(available_bytes)} can be "
            "made available. Nothing was written. Delete files to free space."
        )

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
        added_bytes = self._admit_write(path, key, lambda: len(content))
        try:
            client.put_object(Bucket=self._bucket_name(), Key=key, Body=content)  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

        _record_added_bytes(added_bytes)
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
            if is_reserved_path(self._strip_org_prefix(folder_key)):
                continue
            folder_name = folder_key.rstrip("/").split("/")[-1]
            entries.append({"name": folder_name, "type": "folder", "size": 0, "modified": None})

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

    def walk(self, path: str) -> list[dict]:
        """
        Recursively list every object under ``path`` (no ``Delimiter`` —
        descends through all nested "folders"), org prefix stripped.

        Returns ``list[dict]`` with keys:
          - ``"path"``: object path relative to the org root — the same
            format accepted by ``read``/``write``/``delete``/etc.
          - ``"size"``: object size in bytes.
          - ``"modified"``: ISO-8601 timestamp string, or ``None``.

        ``.keep`` folder markers are skipped. Pagination is handled
        internally — callers get the full flattened listing in one call.
        This is the primitive backing recursive tools (glob/grep/rm -r/
        ls -R/find/du); those tools should use this return shape rather
        than re-deriving directory structure themselves.
        """
        check_storage_permission("walk", path)
        client = self._get_client()
        prefix = self._normalize_key(path)
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        entries: list[dict] = []
        continuation_token: str | None = None

        while True:
            kwargs: dict = {"Bucket": self._bucket_name(), "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            try:
                response = client.list_objects_v2(**kwargs)  # type: ignore[attr-defined]
            except Exception as error:
                self._handle_client_error(error, path)
                raise  # unreachable, satisfies type checker

            for obj in response.get("Contents") or []:
                object_key = obj["Key"]
                object_name = object_key.split("/")[-1]
                relative_path = self._strip_org_prefix(object_key)
                if object_name == ".keep" or is_reserved_path(relative_path):
                    continue
                modified = obj.get("LastModified")
                entries.append(
                    {
                        "path": relative_path,
                        "size": obj.get("Size", 0),
                        "modified": modified.isoformat() if modified else None,
                    }
                )

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

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
                            return bool(response.get("Contents") or response.get("CommonPrefixes"))
                        except Exception:
                            return False
            except ImportError:
                pass
            self._handle_client_error(error, path)
            raise  # unreachable, satisfies type checker

    def delete(self, path: str) -> None:
        check_storage_permission("delete", path)
        client = self._get_client()
        key = self._normalize_key(path)
        try:
            client.delete_object(Bucket=self._bucket_name(), Key=key)  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

        _mutations.append({"op": "delete", "path": key})

    def delete_folder(self, path: str) -> None:
        """
        Delete every object under the folder prefix ``path`` (including
        ``.keep`` markers), using batched ``delete_objects`` calls
        (<=1000 keys/batch) instead of per-key ``delete_object``.

        Records one ``{"op": "delete", "path": key}`` mutation per object
        that S3 actually confirms as deleted — the django `StorageFile`
        index sync (``storage_mutations_handler`` /
        ``StorageFileSync.on_delete``) processes mutations one path at a
        time, so a single folder-level mutation would leave every
        contained file as a ghost row.

        Mutations are recorded batch-by-batch, right after each
        ``delete_objects`` call returns, instead of only after every batch
        has succeeded. This guarantees keys deleted by earlier batches
        stay recorded even if a later batch fails outright or reports
        per-key errors. A batch that comes back HTTP 200 with a per-key
        ``response["Errors"]`` list (boto3's partial-failure shape) has
        those specific keys excluded from the mutation list — S3 is
        explicitly telling us they were not deleted.

        If any keys end up unresolved this way (per-key ``Errors``, across
        one or more batches), this method raises ``RuntimeError`` naming
        the failed keys *after* recording every key that was confirmed
        deleted. A batch call that raises outright still propagates
        immediately via ``_handle_client_error`` (which always re-raises)
        rather than continuing to later batches — but mutations for every
        already-completed batch remain recorded.

        Raises:
            ValueError: ``path`` is empty/root ("", "/", ".").
            FileNotFoundError: nothing exists under the prefix.
            RuntimeError: one or more keys failed to delete (partial
                failure reported via ``response["Errors"]``) — the message
                names/counts the failed keys. Keys that did delete
                successfully (this batch or earlier ones) are still
                recorded as mutations before this is raised.
        """
        normalized = _safe_relative_path(path)
        if normalized == "":
            raise ValueError(f"Refusing to delete root or empty path: '{path}'")

        check_storage_permission("delete", path)
        client = self._get_client()
        bucket = self._bucket_name()
        prefix = self._normalize_key(path).rstrip("/") + "/"

        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict = {"Bucket": bucket, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            try:
                response = client.list_objects_v2(**kwargs)  # type: ignore[attr-defined]
            except Exception as error:
                self._handle_client_error(error, path)
                raise  # unreachable, satisfies type checker

            keys.extend(obj["Key"] for obj in response.get("Contents") or [])

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        if not keys:
            raise FileNotFoundError(f"Not found in storage: {path}")

        batch_size = 1000
        failed_keys: list[str] = []
        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]
            try:
                response = client.delete_objects(  # type: ignore[attr-defined]
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": key} for key in batch]},
                )
            except Exception as error:
                self._handle_client_error(error, path)
                raise  # unreachable, satisfies type checker

            error_keys = {err["Key"] for err in (response.get("Errors") or [])}
            for key in batch:
                if key in error_keys:
                    failed_keys.append(key)
                else:
                    _mutations.append({"op": "delete", "path": key})

        if failed_keys:
            shown = ", ".join(failed_keys[:10])
            remainder = f", and {len(failed_keys) - 10} more" if len(failed_keys) > 10 else ""
            raise RuntimeError(
                f"Failed to delete {len(failed_keys)} object(s) under '{path}': {shown}{remainder}"
            )

    def mkdir(self, path: str) -> None:
        check_storage_permission("mkdir", path)
        client = self._get_client()
        normalized = self._normalize_key(path).rstrip("/")
        keep_key = normalized + "/.keep"
        added_bytes = self._admit_write(path, keep_key, lambda: 0)
        try:
            client.put_object(Bucket=self._bucket_name(), Key=keep_key, Body=b"")  # type: ignore[attr-defined]
        except Exception as error:
            self._handle_client_error(error, path)

        # Mirrors write_bytes' mutation recording. Django's own S3 backend
        # (tables/services/storage_service/s3_backend.py) uses a different
        # empty-folder marker (a trailing-slash zero-byte key, not ".keep")
        # and StorageManager.mkdir never calls a StorageFileSync hook at
        # all — django does not index empty folders as StorageFile rows;
        # they only exist implicitly as a prefix of real file paths. There
        # is no "on_mkdir" sync method and no dedicated mutation op for
        # folder creation. Recording a "write" mutation for the .keep key
        # is the only mechanism this SDK has to make an empty folder
        # visible to django's index at all — storage_mutations_handler
        # treats every "write" mutation uniformly via
        # StorageFileSync.on_upload(org_id, rel_path), regardless of the
        # path, so this is consistent with how every other write in this
        # module is already synced. The tradeoff: an empty folder now
        # surfaces as a StorageFile row named ".keep" rather than not
        # existing in the index at all (matching neither django's own
        # convention, since django never creates one, nor a "no row"
        # outcome). walk() skips ".keep" objects so tool-facing listings
        # never show it.
        _record_added_bytes(added_bytes)
        _mutations.append({"op": "write", "path": keep_key})

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
        added_bytes = self._admit_write(dst, dst_key, lambda: self._stored_size(src_key))
        try:
            client.copy_object(  # type: ignore[attr-defined]
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": src_key},
                Key=dst_key,
            )
        except Exception as error:
            self._handle_client_error(error, src)

        _record_added_bytes(added_bytes)
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

    def read_lines(self, path: str, line_number: int, num_lines: int | None = None) -> str:
        file_info = self.info(path)
        if file_info["size"] > MAX_LINE_READ_BYTES:
            raise StorageSizeLimitError(
                f"File '{path}' exceeds the {MAX_LINE_READ_BYTES // (1024 * 1024)} MB read limit."
            )

        if line_number < 1:
            raise ValueError(f"line_number must be >= 1, got {line_number}.")

        content = self.read(path)
        lines = split_lines(content)

        if line_number > len(lines):
            raise ValueError(
                f"line_number {line_number} is out of range (file has {len(lines)} lines)."
            )

        end_index = line_number - 1 + num_lines if num_lines is not None else len(lines)
        selected = lines[line_number - 1 : end_index]

        return "".join(f"{line_number + idx}: {line}\n" for idx, line in enumerate(selected))

    def count_lines(self, path: str) -> int:
        file_info = self.info(path)
        if file_info["size"] > MAX_LINE_READ_BYTES:
            raise StorageSizeLimitError(
                f"File '{path}' exceeds the {MAX_LINE_READ_BYTES // (1024 * 1024)} MB read limit."
            )

        content = self.read(path)
        return len(split_lines(content))

    def edit_line(self, path: str, line_number: int, expected_text: str, new_text: str) -> None:
        content = self.read(path)
        lines = content.split("\n")

        if line_number < 1 or line_number > len(lines):
            raise ValueError(
                f"line_number {line_number} is out of range (file has {len(lines)} lines)."
            )

        actual = lines[line_number - 1].rstrip("\n")
        expected = expected_text.rstrip("\n")
        if actual != expected:
            raise StorageLineEditMismatchError(
                f"Line {line_number} mismatch: expected {expected!r}, got {actual!r}."
            )

        lines[line_number - 1] = new_text
        self.write(path, "\n".join(lines))

    def append_text(self, path: str, content: str) -> None:
        try:
            existing = self.read(path)
        except FileNotFoundError:
            existing = ""

        self.write(path, existing + content)

    def insert_lines(self, path: str, line_number: int, content: str) -> None:
        """Insert ``content`` as one or more new lines before line
        ``line_number`` (1-based; ``line_count + 1`` appends).

        Uses :func:`split_lines` for both the existing file and the
        inserted ``content`` so a trailing ``"\\n"`` never manufactures a
        phantom blank line. Trailing-newline round-trip fidelity is
        preserved independently of ``content``: the result ends in
        ``"\\n"`` iff the *existing* file did (or didn't exist at all),
        never because the inserted ``content`` happened to end in one.
        """
        if line_number < 1:
            raise ValueError(f"line_number must be >= 1, got {line_number}")

        try:
            existing = self.read(path)
        except FileNotFoundError:
            existing = ""

        keep_trailing_newline = existing == "" or existing.endswith("\n")
        lines = split_lines(existing)
        idx = min(line_number - 1, len(lines))
        # An empty `content` means "insert one blank line" rather than
        # "insert nothing" — split_lines("") would otherwise collapse to [].
        new_lines = split_lines(content) if content != "" else [""]
        merged = lines[:idx] + new_lines + lines[idx:]

        result = "\n".join(merged)
        if keep_trailing_newline:
            result += "\n"
        self.write(path, result)

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
            with suppress(OSError):
                os.unlink(tmp_path)
