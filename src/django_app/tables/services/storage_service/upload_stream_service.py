import asyncio
import tempfile
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from rest_framework.exceptions import APIException, ValidationError
from tables.services.storage_service.archive_formats import ARCHIVE_SUFFIXES
from tables.services.storage_service.archive_limits import ArchiveExtractionGuard
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.path_utils import sanitize_storage_path
from tables.services.storage_service.quota_service import (
    StorageQuotaExceeded,
    commit_under_org_lock,
    remaining_quota,
    stored_size,
)
from tables.validators.file_upload_validator import FileValidator
from utils.logger import logger

# Re-reading a buffered body: small enough that stream_upload's two-part ceiling
# is not pushed up by a third part-sized chunk.
_FILE_READ_CHUNK = 1024 * 1024

# Outside every org_<id>/ prefix, so a half-written overwrite never shows up in a
# listing; abandoned objects (killed worker) want a bucket lifecycle rule.
_STAGING_PREFIX = "_upload_staging"

_NOT_AN_ARCHIVE = object()


class UploadTooLarge(APIException):
    status_code = 413
    default_detail = "Uploaded file is too large."
    default_code = "upload_too_large"


_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.UPLOAD_MAX_CONCURRENCY)
    return _semaphore


def _org_key(org_id: int, rel: str) -> str:
    return f"org_{org_id}/{rel}"


def _staging_key() -> str:
    return f"{_STAGING_PREFIX}/{uuid.uuid4().hex}"


def _safe_dir(path: str) -> str:
    """Normalize the target directory, rejecting anything that escapes the org root."""
    try:
        return sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
    except ValueError as exc:
        raise ValidationError({"path": str(exc)}) from exc


def _strip_archive_suffix(filename: str) -> str:
    low = filename.lower()
    for sfx in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if low.endswith(sfx):
            return filename[: -len(sfx)]
    return filename


def _default_backend():
    from tables.services.storage_service import get_storage_backend

    return get_storage_backend(organization_prefix="")


def _flat_rel(path: str, filename: str) -> str:
    """Canonical storage-relative path, used for BOTH the object key and the row.

    Normalizing only the key (and keeping the caller's spelling in the row) let
    "/etc/passwd" or "a//b.txt" write an object at one path and a StorageFile at
    another, littering the tree with phantom folders like "/" and "./".
    """
    if "/" in filename or "\\" in filename:
        raise ValidationError({"filename": "filename must not contain a path separator."})
    try:
        safe_name = sanitize_storage_path(filename, allow_empty=False)
    except ValueError as exc:
        raise ValidationError({"filename": str(exc)}) from exc
    safe_dir = _safe_dir(path)
    return f"{safe_dir}/{safe_name}" if safe_dir else safe_name


async def _aiter_file(file_obj):
    while chunk := await asyncio.to_thread(file_obj.read, _FILE_READ_CHUNK):
        yield chunk


async def _stream_flat(org_id: int, rel: str, body_iter, declared_size: int | None, backend):
    """Stream one object to `rel` and commit its row; the caller holds the semaphore."""
    max_flat = settings.MAX_STREAM_UPLOAD_FILE_SIZE
    remaining = await sync_to_async(remaining_quota)(org_id, replacing=[rel])

    if declared_size is not None:
        if max_flat is not None and declared_size > max_flat:
            raise UploadTooLarge()
        if declared_size > remaining:
            raise StorageQuotaExceeded()

    def size_guard(total: int) -> None:
        if max_flat is not None and total > max_flat:
            raise UploadTooLarge()
        if total > remaining:
            raise StorageQuotaExceeded()

    target_key = _org_key(org_id, rel)
    # Streaming straight over an existing object would destroy it if the commit
    # then fails, so an overwrite is staged and swapped in once the row commits.
    replacing = await asyncio.to_thread(backend.exists, target_key)
    write_key = _staging_key() if replacing else target_key
    previous_size = await sync_to_async(stored_size)(org_id, [rel]) if replacing else None

    # The stream can outlast any DB timeout: release the connection now and let
    # the commit open a fresh one instead of finding it dead hours later.
    await sync_to_async(close_old_connections)()
    size = await backend.stream_upload(
        write_key, body_iter, part_size=settings.UPLOAD_PART_SIZE, size_guard=size_guard
    )
    try:
        await sync_to_async(commit_under_org_lock)(org_id, [(rel, size)])
    except BaseException:
        await backend.delete_object_async(write_key)
        raise

    if replacing:
        try:
            await asyncio.to_thread(backend.promote_object, write_key, target_key)
        except BaseException:
            logger.exception("Promoting staged upload {} over {} failed", write_key, target_key)
            await backend.delete_object_async(write_key)
            # The old object is still in place: put its size back on the row.
            await sync_to_async(StorageFileSync.on_upload)(org_id, rel, size=previous_size)
            raise

    return {"path": rel, "size": size}


async def ingest_flat(
    org_id: int,
    path: str,
    filename: str,
    body_iter,
    declared_size: int | None,
    *,
    backend=None,
    validator: FileValidator | None = None,
) -> dict:
    """Pipe a non-archive body into MinIO: at most two parts in RAM, then commit."""
    backend = backend or _default_backend()
    validator = validator or FileValidator()
    validator.validate_name(filename, None)
    rel = _flat_rel(path, filename)

    async with _get_semaphore():
        return await _stream_flat(org_id, rel, body_iter, declared_size, backend)


async def ingest_archive(
    org_id: int,
    path: str,
    filename: str,
    body_iter,
    *,
    backend=None,
    validator: FileValidator | None = None,
) -> dict:
    """Buffer the archive (capped at MAX_ARCHIVE_FILE_SIZE), then validate and
    extract it into MinIO off the event loop."""
    backend = backend or _default_backend()
    validator = validator or FileValidator()
    rel = _flat_rel(path, filename)  # reject a bad path/filename before reading the body

    cap = settings.MAX_ARCHIVE_FILE_SIZE
    # Taken before the body is read: buffering is the expensive part of this route.
    async with _get_semaphore():
        # ZIP keeps its index at the end, so the whole archive must be at hand;
        # past one part it spills to disk instead of pinning RAM per request.
        with tempfile.SpooledTemporaryFile(max_size=settings.UPLOAD_PART_SIZE) as spooled:
            total = 0
            async for chunk in body_iter:
                total += len(chunk)
                if total > cap:
                    raise UploadTooLarge()
                spooled.write(chunk)
            spooled.seek(0)

            # Thread-sensitive: its DB work lands on the request's own
            # connection, which the request_finished signal then closes.
            result = await sync_to_async(_process_archive_sync)(
                org_id, path, filename, spooled, backend, validator
            )

            if result is _NOT_AN_ARCHIVE:
                spooled.seek(0)
                return await _stream_flat(org_id, rel, _aiter_file(spooled), total, backend)
            return result


def _read_up_to(reader, limit: int) -> bytes:
    """Read until EOF or limit + 1 bytes, telling a small member from a big one."""
    parts: list[bytes] = []
    got = 0
    while got <= limit:
        chunk = reader.read(limit + 1 - got)
        if not chunk:
            break
        parts.append(chunk)
        got += len(chunk)
    return b"".join(parts)


class _PrefixedReader:
    """Replays the bytes already taken off a member, then reads on."""

    def __init__(self, head: bytes, tail):
        self._head = head
        self._tail = tail

    def read(self, size: int = -1) -> bytes:
        if not self._head:
            return self._tail.read(size)
        if size is None or size < 0:
            out, self._head = self._head + self._tail.read(), b""
            return out
        out, self._head = self._head[:size], self._head[size:]
        return out


def _wait_for_slot(pending: dict[str, Future], limit: int) -> None:
    while len(pending) >= limit:
        done, _ = wait(pending.values(), return_when=FIRST_COMPLETED)
        for rel in [r for r, f in pending.items() if f in done]:
            pending.pop(rel).result()


def _extract_members(org_id, folder_rel, spooled, backend, guard) -> dict[str, int]:
    """Upload every member, overlapping the PUTs of small ones in a bounded pool.

    Members are read in archive order on this thread (zip/tar streams can't be
    read concurrently); only the network calls fan out. A member up to a part is
    buffered and PUT whole, a bigger one streams through upload() inline, so RAM
    stays near workers x part_size."""
    part_size = settings.UPLOAD_PART_SIZE
    workers = settings.ARCHIVE_UPLOAD_CONCURRENCY
    written: dict[str, int] = {}
    pending: dict[str, Future] = {}

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="archive-put") as pool:
        try:
            for safe_name, reader in backend.iter_archive_members_streaming(spooled, guard):
                rel = f"{folder_rel}/{safe_name}"
                key = _org_key(org_id, rel)
                if rel in pending:
                    # A repeated entry name: the later one must win, as it did serially.
                    pending.pop(rel).result()

                head = _read_up_to(reader, part_size)
                if len(head) <= part_size:
                    _wait_for_slot(pending, workers)
                    pending[rel] = pool.submit(backend.put_bytes, key, head)
                    written[rel] = len(head)
                else:
                    written[rel] = backend.upload(key, _PrefixedReader(head, reader)).size

            for future in pending.values():
                future.result()
        except BaseException:
            for future in pending.values():
                future.cancel()
            raise  # leaving the pool waits for PUTs already running before cleanup

    return written


def _process_archive_sync(org_id, path, filename, spooled, backend, validator):
    validator.validate_stream(spooled, filename, None)
    spooled.seek(0)

    # The archive/flat split is made on the file name before the body is read, so a
    # plain file carrying an archive extension (a text dump named .tar.gz, a truncated
    # download) lands here; it is stored as a file instead of failing the request.
    if not StorageManager._is_archive(spooled, filename=filename):
        return _NOT_AN_ARCHIVE
    spooled.seek(0)

    cap = min(settings.MAX_ARCHIVE_UNCOMPRESSED_SIZE, remaining_quota(org_id))
    guard = ArchiveExtractionGuard(max_entries=settings.MAX_ARCHIVE_ENTRIES, max_total_bytes=cap)

    stem = sanitize_storage_path(_strip_archive_suffix(filename), allow_empty=False)
    safe_dir = _safe_dir(path)
    folder_name = f"{stem}-{uuid.uuid4().hex}"
    folder_rel = f"{safe_dir}/{folder_name}" if safe_dir else folder_name

    try:
        written = _extract_members(org_id, folder_rel, spooled, backend, guard)
        commit_under_org_lock(org_id, list(written.items()))
    except BaseException:
        backend.delete(_org_key(org_id, folder_rel))
        raise

    return {"path": folder_rel, "extracted": list(written)}
