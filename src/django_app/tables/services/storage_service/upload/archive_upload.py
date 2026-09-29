import asyncio
import lzma
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Callable

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from rest_framework.exceptions import ValidationError
from tables.exceptions import StoragePathIsFile, StorageUnavailable, UploadTooLarge
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.archive.extraction_guard import ArchiveExtractionGuard
from tables.services.storage_service.archive.inspection import inspect_archive
from tables.services.storage_service.archive.member_upload import upload_archive_members
from tables.services.storage_service.archive.names import strip_archive_suffix
from tables.services.storage_service.path_utils import (
    check_new_name,
    check_path_length,
    sanitize_storage_path,
    storage_key,
)
from tables.services.storage_service.quota import org_free_bytes, record_files_within_quota
from tables.services.storage_service.upload.admission import get_upload_admission
from tables.services.storage_service.upload.file_upload import save_stream
from tables.services.storage_service.upload.guards import (
    storage_errors_as_unavailable,
    within_time_limits,
)
from tables.services.storage_service.upload.target import (
    check_target,
    clean_folder,
    join_storage_path,
    target_path,
)
from tables.validators.file_upload_validator import FileValidator
from utils.logger import logger

# Chunk size for re-reading an already buffered file: well under one part, so
# upload_chunks still holds about one part.
_BUFFERED_READ_CHUNK = 1024 * 1024

# Returned by _unpack_to_storage when the "archive" turned out to be a plain file.
_NOT_AN_ARCHIVE = object()

# Lost folder claims _reserve_folder tolerates; each loss means a concurrent upload
# of the same archive name, so real contention stays far below this.
_MAX_FOLDER_CLAIMS = 100

# Lost claims of one name the store still reports free, after which _reserve_folder
# takes the name as blocked for good rather than held by a claim still in flight.
_MAX_REFUSALS_OF_ONE_NAME = 3


async def _read_in_chunks(file_obj):
    while chunk := await asyncio.to_thread(file_obj.read, _BUFFERED_READ_CHUNK):
        yield chunk


async def upload_archive(
    org_id: int,
    path: str,
    filename: str,
    chunks,
    declared_size: int | None,
    *,
    backend=None,
    validator: FileValidator | None = None,
    authorize_overwrite: Callable[[], None] | None = None,
) -> dict:
    """Collect an archive from the request body (up to MAX_ARCHIVE_FILE_SIZE), check
    it and unpack it into a new folder in object storage; the unpacked size is
    bounded only by the org's free space. Returns {"path", "extracted"}, or
    {"path", "size"} when the file only looked like an archive and was stored as is.

    A real archive never replaces anything, so `authorize_overwrite` (see
    upload_file) runs only when a file stored as is would replace one."""
    backend = backend or get_storage_backend(organization_prefix="")
    validator = validator or FileValidator()
    target = target_path(org_id, path, filename, validator)  # before the body is read

    cap = settings.MAX_ARCHIVE_FILE_SIZE
    # Early rejects before waiting for a slot; the count below stays the real limit,
    # since Content-Length may be missing or lie. No quota check here: the unpacked
    # size is unknown until the archive is read.
    if declared_size is not None and declared_size > cap:
        raise UploadTooLarge()
    await sync_to_async(check_target)(org_id, target, None)
    # No connection may be held through the wait for a slot.
    await sync_to_async(close_old_connections)()
    async with get_upload_admission().admit(org_id):
        with (
            storage_errors_as_unavailable(),
            # ZIP keeps its index at the end, so the whole archive must be at hand;
            # past one part it goes to disk instead of RAM.
            tempfile.SpooledTemporaryFile(max_size=backend.part_size) as buffered,
        ):
            total = 0
            async for chunk in within_time_limits(chunks):
                total += len(chunk)
                if total > cap:
                    raise UploadTooLarge()
                # A write past max_size rolls the buffer over to disk.
                await asyncio.to_thread(buffered.write, chunk)
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
                return await save_stream(
                    org_id,
                    target,
                    _read_in_chunks(buffered),
                    total,
                    backend,
                    authorize_overwrite,
                )
            return result


def _unpack_to_storage(org_id, path, filename, buffered, backend, validator):
    """Validate the buffered archive and unpack it into a new "<name> (n)" folder,
    then write the rows within the quota. On failure exactly the objects this call
    created are removed again, never by name or prefix: a file named like the
    folder ("report" next to "report.zip") or anything another upload put in the
    folder meanwhile is not this call's to delete."""
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
    folder_key = _reserve_folder(org_id, join_storage_path(clean_folder(path), stem), backend)
    folder = folder_key.removeprefix(storage_key(org_id, ""))

    created = [f"{folder_key}/"]  # the marker _reserve_folder claimed
    try:
        # Takes back its own members if it fails.
        sizes = upload_archive_members(
            buffered,
            guard,
            backend,
            folder_key,
            workers=settings.ARCHIVE_UPLOAD_CONCURRENCY,
            check_member=lambda name: check_path_length(org_id, f"{folder}/{name}"),
        )
        created += [f"{folder_key}/{name}" for name in sizes]
        files = [(f"{folder}/{name}", size) for name, size in sizes.items()]
        # A folder with nothing under it exists in object storage only as a marker.
        parents = {name.rsplit("/", i)[0] for name in sizes for i in range(1, name.count("/") + 1)}
        empty_dirs = [d for d in archive_dirs if d not in parents]
        for directory in empty_dirs:
            check_path_length(org_id, f"{folder}/{directory}", is_folder=True)
        for directory in empty_dirs:
            created.append(f"{folder_key}/{directory}/")
            backend.mkdir(f"{folder_key}/{directory}")
        record_files_within_quota(org_id, files, [f"{folder}/{d}" for d in empty_dirs])
    except BaseException:
        backend.discard_keys(created)
        raise

    return {"path": folder, "extracted": [file_path for file_path, _ in files]}


def _reserve_folder(org_id: int, folder: str, backend) -> str:
    """Storage key of the first free "<folder>", "<folder> (1)", ..., claimed with a
    conditional marker write, so two uploads of one archive never share a folder.

    No DB lock is held: the store itself refuses the second claim of a name, and the
    loser probes again, now seeing the winner's marker, so the loop moves on to a
    later name. A name refused _MAX_REFUSALS_OF_ONE_NAME times in a row while the
    probe keeps reporting it free is blocked by something the probe does not see
    (MinIO refuses to write under a file at a parent path): StoragePathIsFile (409).
    The cap only stops a store that refuses every new name from spinning forever.
    ValueError for a name or path the " (n)" suffix made too long, before the store
    sees it."""
    org_prefix = storage_key(org_id, "")
    wanted = storage_key(org_id, folder)
    refused_key, refusals = None, 0
    for _ in range(_MAX_FOLDER_CLAIMS):
        key = backend.unique_key(wanted, is_folder=True)
        candidate = key.removeprefix(org_prefix)
        check_new_name(candidate.rpartition("/")[2])
        check_path_length(org_id, candidate, is_folder=True)
        if backend.claim_folder(key):
            return key
        refusals = refusals + 1 if key == refused_key else 1
        refused_key = key
        if refusals == _MAX_REFUSALS_OF_ONE_NAME:
            raise StoragePathIsFile(folder)
    logger.error(
        "No free folder name for {!r} after {} claims; the object store refused every one",
        folder,
        _MAX_FOLDER_CLAIMS,
    )
    raise StorageUnavailable()
