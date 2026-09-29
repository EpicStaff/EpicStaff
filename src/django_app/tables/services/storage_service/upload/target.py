from collections.abc import Callable

from rest_framework.exceptions import ValidationError
from tables.exceptions import StoragePathIsFile
from tables.models import StorageFile
from tables.services.storage_service.path_utils import (
    check_new_name,
    check_path_length,
    sanitize_storage_path,
)
from tables.validators.file_upload_validator import FileValidator


def join_storage_path(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def clean_folder(path: str) -> str:
    """Normalized target folder ("" = storage root); 400 if it escapes the org root."""
    try:
        folder = sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
        if folder:
            check_new_name(folder)
    except ValueError as exc:
        raise ValidationError({"path": str(exc)}) from exc
    return folder


def target_path(org_id: int, path: str, filename: str, validator: FileValidator) -> str:
    """Validate the file name and build the one path used for both the object and its row."""
    validator.validate_name(filename)
    if "/" in filename or "\\" in filename:
        raise ValidationError({"filename": "filename must not contain a path separator."})
    try:
        safe_name = sanitize_storage_path(filename, allow_empty=False)
        check_new_name(safe_name)
    except ValueError as exc:
        raise ValidationError({"filename": str(exc)}) from exc
    target = join_storage_path(clean_folder(path), safe_name)
    try:
        check_path_length(org_id, target)
    except ValueError as exc:
        raise ValidationError({"path": str(exc)}) from exc
    return target


def check_target(org_id: int, target: str, authorize_overwrite: Callable[[], None] | None) -> None:
    """Early reject from StorageFile rows: 409 if a parent is a file; authorize an overwrite."""
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
