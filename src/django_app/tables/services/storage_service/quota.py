from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from rbac.models import Organization
from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services.storage_service.db_sync import StorageFileSync


def _total_size(rows) -> int:
    return rows.aggregate(s=Sum("size"))["s"] or 0


def org_used_bytes(org_id: int) -> int:
    """How many bytes the org's files take, summed from StorageFile rows.

    Files in the recycle bin count too: their bytes are still stored, and
    leaving them out would let an org go past its quota by deleting and
    uploading again.
    """
    return _total_size(StorageFile.all_objects.filter(org_id=org_id))


def size_of_paths(org_id: int, paths) -> int:
    """Summed size of the org's files at these paths (0 for paths with no row)."""
    return _total_size(StorageFile.objects.filter(org_id=org_id, path__in=list(paths)))


def org_free_bytes(org_id: int, replacing=()) -> int:
    """Bytes the org may still upload; files at `replacing` count as freed."""
    freed = size_of_paths(org_id, replacing) if replacing else 0
    return max(0, settings.ORG_STORAGE_QUOTA - org_used_bytes(org_id) + freed)


def is_over_quota(org_id: int) -> bool:
    return org_used_bytes(org_id) > settings.ORG_STORAGE_QUOTA


def ensure_fits_quota(org_id: int, size: int, replacing=()) -> None:
    """Raise 413 unless `size` more bytes fit; final only under record_files_within_quota's lock."""
    if size > org_free_bytes(org_id, replacing=replacing):
        raise StorageQuotaExceeded()


def record_files_within_quota(org_id: int, files: list[tuple[str, int]], folders=()) -> None:
    """Write rows for stored files [(path, size)] and empty folders, or raise 413 if they don't fit.
    The org row lock serializes the quota check across concurrent writers of one org."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        ensure_fits_quota(
            org_id, sum(size for _, size in files), replacing=[path for path, _ in files]
        )
        StorageFileSync.on_bulk_upload(org_id, files, folders)
