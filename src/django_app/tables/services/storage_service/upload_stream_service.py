import asyncio
import functools
import lzma
import tarfile
import tempfile
import zipfile
import zlib

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, transaction
from rest_framework.exceptions import ValidationError
from tables.exceptions import StorageQuotaExceeded, UploadTooLarge
from tables.models import Organization, StorageFile
from tables.services.storage_service.archive_formats import (
    inspect_archive,
    strip_archive_suffix,
)
from tables.services.storage_service.archive_limits import ArchiveExtractionGuard
from tables.services.storage_service.archive_member_upload import upload_archive_members
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.path_utils import check_new_name, sanitize_storage_path
from tables.services.storage_service.quota_service import (
    org_free_bytes,
    record_files_within_quota,
)
from tables.validators.file_upload_validator import FileValidator

# Chunk size for re-reading an already buffered file: well under one part, so
# upload_chunks still holds about one part.
_BUFFERED_READ_CHUNK = 1024 * 1024

# Returned by _unpack_to_storage when the "archive" turned out to be a plain file.
_NOT_AN_ARCHIVE = object()

_slots: asyncio.Semaphore | None = None


def _upload_slots() -> asyncio.Semaphore:
    """Caps uploads running at once in this worker (UPLOAD_MAX_CONCURRENCY)."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(settings.UPLOAD_MAX_CONCURRENCY)
    return _slots


@functools.cache
def _storage_backend():
    """One S3 client per process; boto3 clients are thread-safe."""
    from tables.services.storage_service import get_storage_backend

    return get_storage_backend(organization_prefix="")


def _storage_key(org_id: int, path: str) -> str:
    return f"org_{org_id}/{path}"


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def _clean_folder(path: str) -> str:
    """Normalized target folder ("" = storage root); 400 if it escapes the org root."""
    try:
        folder = sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
        if folder:
            check_new_name(folder)
    except ValueError as exc:
        raise ValidationError({"path": str(exc)}) from exc
    return folder


def _target_path(path: str, filename: str, validator: FileValidator) -> str:
    """Check the name (blocked extensions, path tricks) and build the one path used
    for both the storage object and its StorageFile row, so the two never differ."""
    validator.validate_name(filename)
    if "/" in filename or "\\" in filename:
        raise ValidationError({"filename": "filename must not contain a path separator."})
    try:
        safe_name = sanitize_storage_path(filename, allow_empty=False)
        check_new_name(safe_name)
    except ValueError as exc:
        raise ValidationError({"filename": str(exc)}) from exc
    return _join(_clean_folder(path), safe_name)


async def _read_in_chunks(file_obj):
    while chunk := await asyncio.to_thread(file_obj.read, _BUFFERED_READ_CHUNK):
        yield chunk


async def upload_file(
    org_id: int,
    path: str,
    filename: str,
    chunks,
    declared_size: int | None,
    *,
    backend=None,
    validator: FileValidator | None = None,
) -> dict:
    """Stream a plain file from the request body (`chunks`) into MinIO and record it.
    Returns {"path", "size"}."""
    backend = backend or _storage_backend()
    target = _target_path(path, filename, validator or FileValidator())
    async with _upload_slots():
        return await _save_stream(org_id, target, chunks, declared_size, backend)


async def upload_archive(
    org_id: int,
    path: str,
    filename: str,
    chunks,
    *,
    backend=None,
    validator: FileValidator | None = None,
) -> dict:
    """Collect an archive from the request body (up to MAX_ARCHIVE_FILE_SIZE), check
    it and unpack it into a new folder in MinIO; the unpacked size is bounded only
    by the org's free space. Returns {"path", "extracted"}, or
    {"path", "size"} when the file only looked like an archive and was stored as is."""
    backend = backend or _storage_backend()
    validator = validator or FileValidator()
    target = _target_path(path, filename, validator)  # before the body is read

    cap = settings.MAX_ARCHIVE_FILE_SIZE
    async with _upload_slots():
        # ZIP keeps its index at the end, so the whole archive must be at hand;
        # past one part it goes to disk instead of RAM.
        with tempfile.SpooledTemporaryFile(max_size=settings.UPLOAD_PART_SIZE) as buffered:
            total = 0
            async for chunk in chunks:
                total += len(chunk)
                if total > cap:
                    raise UploadTooLarge()
                buffered.write(chunk)
            buffered.seek(0)

            try:
                # Thread-sensitive, so its DB work uses the request's own connection,
                # which the request_finished signal closes.
                result = await sync_to_async(_unpack_to_storage)(
                    org_id, path, filename, buffered, backend, validator
                )
            except (
                ValueError,
                zipfile.BadZipFile,
                tarfile.TarError,
                EOFError,
                zlib.error,
                lzma.LZMAError,
            ) as exc:
                # zip bomb, zip-slip, symlink, encrypted or corrupt archive: the
                # client's fault, so 400 with the reason rather than a server error.
                # Unlabelled: the reason already names the archive.
                raise ValidationError(str(exc)) from exc

            if result is _NOT_AN_ARCHIVE:
                buffered.seek(0)
                return await _save_stream(org_id, target, _read_in_chunks(buffered), total, backend)
            return result


async def _save_stream(org_id: int, target: str, chunks, declared_size: int | None, backend):
    """Upload `chunks` to `target` and write its StorageFile row within the quota.
    The row is written after the last byte but before MinIO commits the object,
    so a rejected row aborts the upload and an overwritten file stays intact.
    The caller holds an upload slot."""
    max_size = settings.MAX_STREAM_UPLOAD_FILE_SIZE
    free = await sync_to_async(org_free_bytes)(org_id, replacing=[target])

    def reject_if_too_big(size: int) -> None:
        if max_size is not None and size > max_size:
            raise UploadTooLarge()
        if size > free:
            raise StorageQuotaExceeded()

    if declared_size is not None:
        reject_if_too_big(declared_size)

    previous_row = await sync_to_async(_file_row_size)(org_id, target)
    row_written = False

    async def write_row(size: int) -> None:
        nonlocal row_written
        await sync_to_async(record_files_within_quota)(org_id, [(target, size)])
        row_written = True

    # The stream can outlast any DB timeout: release the connection now and let
    # the row write open a fresh one.
    await sync_to_async(close_old_connections)()
    try:
        size = await backend.upload_chunks(
            _storage_key(org_id, target),
            chunks,
            part_size=settings.UPLOAD_PART_SIZE,
            size_guard=reject_if_too_big,
            before_commit=write_row,
        )
    except BaseException:
        if row_written:
            # MinIO failed to commit after the row went in: the old object (or
            # none) is still there, so the row goes back to match it.
            await sync_to_async(_restore_file_row)(org_id, target, previous_row)
        raise

    return {"path": target, "size": size}


def _file_row_size(org_id: int, path: str) -> list[int | None]:
    """[size] of the file row at `path`, or [] when there is none."""
    return list(
        StorageFile.objects.filter(org_id=org_id, path=path, item_type="file").values_list(
            "size", flat=True
        )
    )


def _restore_file_row(org_id: int, path: str, previous_row: list[int | None]) -> None:
    if previous_row:
        StorageFileSync.on_upload(org_id, path, size=previous_row[0])
    else:
        StorageFileSync.on_delete(org_id, path)


def _unpack_to_storage(org_id, path, filename, buffered, backend, validator):
    """Validate the buffered archive and unpack it into a new "<name> (n)" folder,
    then write the rows within the quota; on failure the folder is removed again."""
    free = org_free_bytes(org_id)

    # The route was picked by file name alone, so a plain file with an archive
    # suffix (a text dump named .tar.gz, a truncated download) lands here too.
    archive_dirs = inspect_archive(
        buffered,
        filename,
        max_entries=settings.MAX_ARCHIVE_ENTRIES,
        free_bytes=free,
        is_blocked=validator.is_executable_filename,
    )
    if archive_dirs is None:
        return _NOT_AN_ARCHIVE

    # ZIP sizes are only declared: the guard counts the bytes really inflated.
    guard = ArchiveExtractionGuard(max_entries=settings.MAX_ARCHIVE_ENTRIES, max_total_bytes=free)

    stem = sanitize_storage_path(strip_archive_suffix(filename), allow_empty=False)
    folder_key = _reserve_folder(org_id, _join(_clean_folder(path), stem), backend)
    folder = folder_key.removeprefix(_storage_key(org_id, ""))

    try:
        sizes = upload_archive_members(
            buffered,
            guard,
            backend,
            folder_key,
            part_size=settings.UPLOAD_PART_SIZE,
            workers=settings.ARCHIVE_UPLOAD_CONCURRENCY,
        )
        files = [(f"{folder}/{name}", size) for name, size in sizes.items()]
        # A folder with nothing under it exists in MinIO only as a marker object.
        parents = {name.rsplit("/", i)[0] for name in sizes for i in range(1, name.count("/") + 1)}
        empty_dirs = [d for d in archive_dirs if d not in parents]
        for directory in empty_dirs:
            backend.mkdir(f"{folder_key}/{directory}")
        record_files_within_quota(org_id, files, [f"{folder}/{d}" for d in empty_dirs])
    except BaseException:
        backend.delete(folder_key)
        raise

    return {"path": folder, "extracted": [file_path for file_path, _ in files]}


def _reserve_folder(org_id: int, folder: str, backend) -> str:
    """Storage key of the first free "<folder>", "<folder> (1)", ..., claimed with a
    marker under the org lock so two uploads of one archive never share a folder."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        key = backend.unique_key(_storage_key(org_id, folder), is_folder=True)
        backend.mkdir(key)
    return key
