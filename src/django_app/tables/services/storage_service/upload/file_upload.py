import datetime
from collections.abc import Callable
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, transaction
from rbac.authorship import RecordedLastEdit, restore_last_edits
from rbac.models import Organization
from tables.exceptions import StorageQuotaExceeded, UploadTooLarge
from tables.models import StorageFile
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.path_utils import storage_key
from tables.services.storage_service.quota import org_free_bytes, record_files_within_quota
from tables.services.storage_service.upload.admission import get_upload_admission
from tables.services.storage_service.upload.guards import (
    storage_errors_as_unavailable,
    within_time_limits,
)
from tables.services.storage_service.upload.target import check_target, target_path
from tables.validators.file_upload_validator import FileValidator
from utils.logger import logger


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
    user: object | None = None,
) -> dict:
    """Stream a plain file from the request body into object storage and record it.
    `authorize_overwrite()` may raise to refuse replacing a file; None replaces silently.
    `user` authors the new rows and last edits the file; a replaced file keeps its author."""
    backend = backend or get_storage_backend(organization_prefix="")
    target = target_path(org_id, path, filename, validator or FileValidator())
    max_size = settings.MAX_STREAM_UPLOAD_FILE_SIZE
    # Early rejects before waiting for a slot; save_stream enforces them for real.
    if declared_size is not None and max_size is not None and declared_size > max_size:
        raise UploadTooLarge()
    await sync_to_async(check_target)(org_id, target, authorize_overwrite)
    # No connection may be held through the wait for a slot.
    await sync_to_async(close_old_connections)()
    async with get_upload_admission().admit(org_id):
        with storage_errors_as_unavailable():
            return await save_stream(
                org_id,
                target,
                within_time_limits(chunks),
                declared_size,
                backend,
                authorize_overwrite,
                user=user,
            )


async def save_stream(
    org_id: int,
    target: str,
    chunks,
    declared_size: int | None,
    backend,
    authorize_overwrite: Callable[[], None] | None,
    *,
    user: object | None = None,
):
    """Upload `chunks` to `target` and write its StorageFile row within the quota.
    The row is written before the store commits, so a rejected row aborts the upload."""
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
    replaced_row: _ReplacedFile | None = None

    async def write_row(size: int) -> None:
        nonlocal written_size, replaced_row
        replaced_row = await sync_to_async(_write_file_row)(
            org_id, target, size, authorize_overwrite, user
        )
        written_size = size

    # The stream can outlast any DB timeout, so release the connection now.
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


@dataclass(frozen=True)
class _ReplacedFile:
    """The file row an upload wrote over, as it was before: its size and last edit."""

    size: int | None
    # (edited_by_id, edited_at), or None when the file had never been edited.
    last_edit: tuple[int | None, datetime.datetime] | None


def _write_file_row(
    org_id: int,
    target: str,
    size: int,
    authorize_overwrite: Callable[[], None] | None,
    user: object | None,
) -> _ReplacedFile | None:
    """Write the upload's row under the org lock; return what it replaced, or None."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        replaced_row = (
            StorageFile.objects.filter(org_id=org_id, path=target, item_type="file")
            .prefetch_related("last_edits")
            .first()
        )
        if replaced_row is not None and authorize_overwrite is not None:
            authorize_overwrite()
        record_files_within_quota(org_id, [(target, size)], user=user)
    if replaced_row is None:
        return None
    last_edit = next(iter(replaced_row.last_edits.all()), None)
    return _ReplacedFile(
        size=replaced_row.size,
        last_edit=(last_edit.edited_by_id, last_edit.edited_at) if last_edit else None,
    )


def _undo_file_row(
    org_id: int,
    target: str,
    written_size: int,
    replaced_row: _ReplacedFile | None,
    backend,
) -> None:
    """After a failed upload, bring the row at `target` back in line with what the store holds.
    A replaced file whose object is still there gets back its size and its last edit."""
    try:
        stored = backend.head_file(storage_key(org_id, target))
    except Exception:
        # The store can't be asked; the failure most likely means it did not commit.
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
            if row.update(size=replaced_row.size):
                _restore_last_edit(
                    StorageFile.objects.get(org_id=org_id, path=target, item_type="file"),
                    replaced_row.last_edit,
                )
        else:
            row.delete()


def _restore_last_edit(
    file_row: StorageFile, last_edit: tuple[int | None, datetime.datetime] | None
) -> None:
    if last_edit is None:
        file_row.last_edits.all().delete()
        return
    edited_by_id, edited_at = last_edit
    restore_last_edits([RecordedLastEdit(file_row, edited_by_id, edited_at)])
