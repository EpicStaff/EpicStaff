import asyncio
import contextlib
import lzma
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Callable

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, transaction
from rbac.models import Organization
from rest_framework.exceptions import ValidationError
from tables.exceptions import (
    StoragePathIsFile,
    StorageQuotaExceeded,
    StorageUnavailable,
    UploadDurationExceeded,
    UploadIdleTimeout,
    UploadTooLarge,
)
from tables.models import StorageFile
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.archive_formats import (
    ARCHIVE_SUFFIXES,
    DOCUMENT_EXTENSIONS,
    inspect_archive,
    strip_archive_suffix,
)
from tables.services.storage_service.archive_limits import ArchiveExtractionGuard
from tables.services.storage_service.archive_member_upload import upload_archive_members
from tables.services.storage_service.base import StorageUnreachable
from tables.services.storage_service.path_utils import (
    check_new_name,
    check_path_length,
    sanitize_storage_path,
    storage_key,
)
from tables.services.storage_service.quota_service import (
    org_free_bytes,
    record_files_within_quota,
)
from tables.services.storage_service.upload_admission import UploadAdmission
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

_admission: UploadAdmission | None = None


def _upload_admission() -> UploadAdmission:
    """This worker's gate over running uploads, built from settings on first use."""
    global _admission
    if _admission is None:
        _admission = UploadAdmission(
            max_concurrency=settings.UPLOAD_MAX_CONCURRENCY,
            per_org_limit=settings.UPLOAD_MAX_CONCURRENCY_PER_ORG,
            slot_timeout=settings.UPLOAD_SLOT_TIMEOUT,
        )
    return _admission


@contextlib.contextmanager
def _storage_errors_as_unavailable():
    """Object storage down, timing out or failing on its side (StorageUnreachable)
    is an outage, not a bug in this request: StorageUnavailable (503). Any other
    storage error (bad credentials, missing bucket) is a misconfiguration and
    stays an unexpected error."""
    try:
        yield
    except StorageUnreachable as exc:
        logger.exception("Streaming upload failed: object storage unreachable")
        raise StorageUnavailable() from exc


async def _within_time_limits(chunks):
    """Pass `chunks` through, aborting when the client sends nothing for
    UPLOAD_IDLE_TIMEOUT (slow-loris guard) or the upload outlives
    UPLOAD_MAX_DURATION (kept under the object storage's stale-upload expiry,
    which would otherwise drop the parts of a still-running multipart upload).

    Only time spent waiting for the client counts as idle: while a part goes
    to object storage nothing is read, and the client is merely back-pressured."""
    loop = asyncio.get_running_loop()
    idle_timeout = settings.UPLOAD_IDLE_TIMEOUT
    max_duration = settings.UPLOAD_MAX_DURATION
    deadline = loop.time() + max_duration
    iterator = aiter(chunks)
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise UploadDurationExceeded(max_duration)
        try:
            async with asyncio.timeout(min(idle_timeout, remaining)):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            return
        except TimeoutError:
            if remaining <= idle_timeout:
                raise UploadDurationExceeded(max_duration) from None
            raise UploadIdleTimeout(idle_timeout) from None
        yield chunk


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


def _target_path(org_id: int, path: str, filename: str, validator: FileValidator) -> str:
    """Check the name (blocked extensions, path tricks, length) and build the one path
    used for both the storage object and its StorageFile row, so the two never differ."""
    validator.validate_name(filename)
    if "/" in filename or "\\" in filename:
        raise ValidationError({"filename": "filename must not contain a path separator."})
    try:
        safe_name = sanitize_storage_path(filename, allow_empty=False)
        check_new_name(safe_name)
    except ValueError as exc:
        raise ValidationError({"filename": str(exc)}) from exc
    target = _join(_clean_folder(path), safe_name)
    try:
        check_path_length(org_id, target)
    except ValueError as exc:
        raise ValidationError({"path": str(exc)}) from exc
    return target


def _check_target(org_id: int, target: str, authorize_overwrite: Callable[[], None] | None) -> None:
    """Early rejects from the StorageFile rows, before the upload waits for a slot:
    StoragePathIsFile (409) when a folder on the way to `target` is a file, and
    `authorize_overwrite()` when a file is already at `target`."""
    segments = target.split("/")
    parents = ["/".join(segments[:depth]) for depth in range(1, len(segments))]
    existing_files = set(
        StorageFile.objects.filter(
            org_id=org_id, item_type="file", path__in=[*parents, target]
        ).values_list("path", flat=True)
    )
    if existing_files.intersection(parents):
        raise StoragePathIsFile(target.rpartition("/")[0])
    if authorize_overwrite is not None and target in existing_files:
        authorize_overwrite()


async def _read_in_chunks(file_obj):
    while chunk := await asyncio.to_thread(file_obj.read, _BUFFERED_READ_CHUNK):
        yield chunk


def upload_limits(org_id: int) -> dict:
    """What the streaming upload will enforce for this org, so a client can skip a
    doomed file before sending it. A name is routed as an archive iff it ends with
    an archive suffix and not with a document extension (is_archive_name).
    `free_bytes` ignores uploads still running and credits no file an upload
    would overwrite. `upload_path` is where to POST the file (DJANGO_UPLOAD_STREAM_PATH)."""
    return {
        "upload_path": settings.UPLOAD_STREAM_PATH,
        "max_file_size": settings.MAX_STREAM_UPLOAD_FILE_SIZE,
        "max_archive_size": settings.MAX_ARCHIVE_FILE_SIZE,
        "free_bytes": org_free_bytes(org_id),
        "archive_suffixes": sorted(ARCHIVE_SUFFIXES),
        "document_extensions": sorted(DOCUMENT_EXTENSIONS),
    }


async def upload_file(
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
    """Stream a plain file from the request body (`chunks`) into object storage and
    record it. Returns {"path", "size"}.

    `authorize_overwrite()` runs when a file already exists at the target and raises
    to refuse replacing it; without it an existing file is replaced silently."""
    backend = backend or get_storage_backend(organization_prefix="")
    target = _target_path(org_id, path, filename, validator or FileValidator())
    max_size = settings.MAX_STREAM_UPLOAD_FILE_SIZE
    # Early rejects before waiting for a slot; _save_stream checks the size, the
    # quota and the overwrite for real.
    if declared_size is not None and max_size is not None and declared_size > max_size:
        raise UploadTooLarge()
    await sync_to_async(_check_target)(org_id, target, authorize_overwrite)
    # No connection may be held through the wait for a slot.
    await sync_to_async(close_old_connections)()
    async with _upload_admission().admit(org_id):
        with _storage_errors_as_unavailable():
            return await _save_stream(
                org_id,
                target,
                _within_time_limits(chunks),
                declared_size,
                backend,
                authorize_overwrite,
            )


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
    target = _target_path(org_id, path, filename, validator)  # before the body is read

    cap = settings.MAX_ARCHIVE_FILE_SIZE
    # Early rejects before waiting for a slot; the count below stays the real limit,
    # since Content-Length may be missing or lie. No quota check here: the unpacked
    # size is unknown until the archive is read.
    if declared_size is not None and declared_size > cap:
        raise UploadTooLarge()
    await sync_to_async(_check_target)(org_id, target, None)
    # No connection may be held through the wait for a slot.
    await sync_to_async(close_old_connections)()
    async with _upload_admission().admit(org_id):
        with (
            _storage_errors_as_unavailable(),
            # ZIP keeps its index at the end, so the whole archive must be at hand;
            # past one part it goes to disk instead of RAM.
            tempfile.SpooledTemporaryFile(max_size=backend.part_size) as buffered,
        ):
            total = 0
            async for chunk in _within_time_limits(chunks):
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
                return await _save_stream(
                    org_id,
                    target,
                    _read_in_chunks(buffered),
                    total,
                    backend,
                    authorize_overwrite,
                )
            return result


async def _save_stream(
    org_id: int,
    target: str,
    chunks,
    declared_size: int | None,
    backend,
    authorize_overwrite: Callable[[], None] | None,
):
    """Upload `chunks` to `target` and write its StorageFile row within the quota.
    The row is written after the last byte but before the store commits the object,
    so a rejected row (quota, refused overwrite) aborts the upload and an overwritten
    file stays intact. The caller holds an upload slot."""
    max_size = settings.MAX_STREAM_UPLOAD_FILE_SIZE
    free = await sync_to_async(org_free_bytes)(org_id, replacing=[target])

    def reject_if_too_big(size: int) -> None:
        if max_size is not None and size > max_size:
            raise UploadTooLarge()
        if size > free:
            raise StorageQuotaExceeded()

    if declared_size is not None:
        reject_if_too_big(declared_size)

    written_size: int | None = None
    replaced_row: tuple[int | None] | None = None

    async def write_row(size: int) -> None:
        nonlocal written_size, replaced_row
        replaced_row = await sync_to_async(_write_file_row)(
            org_id, target, size, authorize_overwrite
        )
        written_size = size

    # The stream can outlast any DB timeout: release the connection now and let
    # the row write open a fresh one.
    await sync_to_async(close_old_connections)()
    try:
        size = await backend.upload_chunks(
            storage_key(org_id, target),
            chunks,
            size_guard=reject_if_too_big,
            before_commit=write_row,
        )
    except BaseException:
        if written_size is not None:
            await sync_to_async(_undo_file_row)(org_id, target, written_size, replaced_row, backend)
        raise

    return {"path": target, "size": size}


def _write_file_row(
    org_id: int, target: str, size: int, authorize_overwrite: Callable[[], None] | None
) -> tuple[int | None] | None:
    """Write the upload's file row within the quota; returns (size,) of
    the file row it replaced, or None. Read under the org lock that
    record_files_within_quota holds for the write, so it is the row this write really
    replaced even while other uploads of the same path run, and the overwrite is
    authorized against the file that is really there."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        replaced_row = (
            StorageFile.objects.filter(org_id=org_id, path=target, item_type="file")
            .values_list("size")
            .first()
        )
        if replaced_row is not None and authorize_overwrite is not None:
            authorize_overwrite()
        record_files_within_quota(org_id, [(target, size)])
    return replaced_row


def _undo_file_row(
    org_id: int,
    target: str,
    written_size: int,
    replaced_row: tuple[int | None] | None,
    backend,
) -> None:
    """Put the row at `target` back in line with the store after the upload failed
    once its row was written. The failure can be ambiguous (a timeout after the
    store committed), so the store decides: the new row stays when the object there
    has the new size, the replaced row comes back as it was when the old object is
    there, and the row goes when nothing is. A row no longer at the new size was
    written by another upload since and is left alone."""
    try:
        stored = backend.head_file(storage_key(org_id, target))
    except Exception:
        # The store can't be asked. The error being re-raised most likely means it
        # did not commit, so the old state is the best guess.
        logger.exception("Could not check {} after a failed upload", target)
        object_there = replaced_row is not None
    else:
        if stored is not None and stored.size == written_size:
            return
        object_there = stored is not None

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        row = StorageFile.objects.filter(
            org_id=org_id, path=target, item_type="file", size=written_size
        )
        if replaced_row is not None and object_there:
            row.update(size=replaced_row[0])
        else:
            row.delete()


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
    folder_key = _reserve_folder(org_id, _join(_clean_folder(path), stem), backend)
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
