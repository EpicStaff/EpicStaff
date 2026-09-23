from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from tables.exceptions import StorageQuotaExceeded
from tables.models import Organization, StorageFile
from tables.services.storage_service.db_sync import StorageFileSync


def _total_size(rows) -> int:
    return rows.aggregate(s=Sum("size"))["s"] or 0


def org_used_bytes(org_id: int) -> int:
    """How many bytes the org's files take, summed from StorageFile rows."""
    return _total_size(StorageFile.objects.filter(org_id=org_id))


def size_of_paths(org_id: int, paths) -> int:
    """Summed size of the org's files at these paths (0 for paths with no row)."""
    return _total_size(StorageFile.objects.filter(org_id=org_id, path__in=list(paths)))


def org_free_bytes(org_id: int, replacing=()) -> int:
    """Bytes the org may still upload. Files at `replacing` count as freed,
    since an overwrite only costs the size difference."""
    freed = size_of_paths(org_id, replacing) if replacing else 0
    return max(0, settings.ORG_STORAGE_QUOTA - org_used_bytes(org_id) + freed)


def record_files_within_quota(org_id: int, files: list[tuple[str, int]], folders=()) -> None:
    """Write StorageFile rows for already-uploaded files [(path, size)] and empty
    `folders`, or raise 413 if the files no longer fit. The org row lock makes
    concurrent uploads of one org check the quota one after another."""
    total = sum(size for _, size in files)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        if total > org_free_bytes(org_id, replacing=[path for path, _ in files]):
            raise StorageQuotaExceeded()
        StorageFileSync.on_bulk_upload(org_id, files, folders)
