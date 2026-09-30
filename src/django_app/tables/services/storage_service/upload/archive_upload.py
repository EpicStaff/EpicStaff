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
from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
)
from tables.services.storage_service.archive_unpacking.inspection import inspect_archive
from tables.services.storage_service.archive_unpacking.names import strip_archive_suffix
from tables.services.storage_service.path_utils import (
    check_new_name,
    check_path_length,
    sanitize_storage_path,
    storage_key,
)
from tables.services.storage_service.quota import org_free_bytes, record_files_within_quota
from tables.services.storage_service.upload.admission import get_upload_admission
from tables.services.storage_service.upload.archive_members import upload_archive_members
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

# Well under one part, so upload_chunks still holds about one part.
_BUFFERED_READ_CHUNK = 1024 * 1024

# Returned by _unpack_to_storage when the "archive" turned out to be a plain file.
_NOT_AN_ARCHIVE = object()

# Lost folder claims _reserve_folder tolerates before giving up.
_MAX_FOLDER_CLAIMS = 100

# Refusals of a name the store reports free, after which the name counts as blocked.
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
    """Unpack an uploaded archive into a new storage folder, or store it as is if not an archive."""
    backend = backend or get_storage_backend(organization_prefix="")
    validator = validator or FileValidator()
    target = target_path(org_id, path, filename, validator)  # before the body is read

    cap = settings.MAX_ARCHIVE_FILE_SIZE
    # Early rejects before waiting for a slot; Content-Length may lie, the count below is the limit.
    if declared_size is not None and declared_size > cap:
        raise UploadTooLarge()
    await sync_to_async(check_target)(org_id, target, None)
    # No connection may be held through the wait for a slot.
    await sync_to_async(close_old_connections)()
    async with get_upload_admission().admit(org_id):
        with (
            storage_errors_as_unavailable(),
            # ZIP keeps its index at the end, so buffer it all; past one part it spills to disk.
            tempfile.SpooledTemporaryFile(max_size=backend.part_size) as buffered,
        ):
            total = 0
            # The request body is first read here, with idle and total time limits.
            async for chunk in within_time_limits(chunks):
                total += len(chunk)
                # 413 once the bytes actually received pass the archive cap.
                if total > cap:
                    raise UploadTooLarge()
                # Buffer the chunk; past one part the buffer moves to disk.
                await asyncio.to_thread(buffered.write, chunk)
            buffered.seek(0)

            try:
                # Thread-sensitive, so its DB work uses the request's connection.
                # Validate the archive, unpack it into storage and write its rows;
                # returns the response {"path", "extracted"} or _NOT_AN_ARCHIVE.
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
                # A bad archive (bomb, zip-slip, symlink, encrypted, corrupt) is a 400.
                raise ValidationError(str(exc)) from exc

            if result is _NOT_AN_ARCHIVE:
                buffered.seek(0)
                # Not an archive: store the buffer as a plain file, read back in 1 MB chunks.
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
    """Validate the buffered archive, unpack it into a new "<name> (n)" folder and record it.
    On failure only the objects this call created are removed, never by name or prefix."""
    free = org_free_bytes(org_id)

    # The route is picked by name alone, so a plain file with an archive suffix lands here too.
    # Headers only, nothing is unpacked: entries, names, declared size vs. quota, executables.
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
        # Unpack one member at a time and send it to storage right away:
        # up to one part in a single PUT (several in parallel), larger ones as multipart.
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
    """Claim the first free "<folder>", "<folder> (1)", ... with a marker write; return its key.
    The store refuses a second claim of a name, so two uploads never share a folder."""
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
