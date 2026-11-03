from collections.abc import Mapping

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from rbac.models import Organization
from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services.storage_service.dataclasses import BinPurgeGrant, PurgedBinEntry
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.recycle_bin import StorageRecycleBinService


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


def _shortfall(org_id: int, size: int, replacing=()) -> int:
    """Bytes missing for `size` more to fit; zero or less when they fit."""
    freed = size_of_paths(org_id, replacing) if replacing else 0
    return size - (settings.ORG_STORAGE_QUOTA - org_used_bytes(org_id) + freed)


def org_free_bytes(org_id: int, replacing=()) -> int:
    """Bytes the org may still upload; files at `replacing` count as freed."""
    return max(0, -_shortfall(org_id, 0, replacing))


def org_writable_bytes(org_id: int, replacing=(), *, bin_purge: BinPurgeGrant | None) -> int:
    """Bytes a write may add: the free bytes, plus what purging the org's storage bin frees
    when the write holds a `bin_purge` grant."""
    purgeable = StorageRecycleBinService.binned_bytes(org_id) if bin_purge is not None else 0
    return max(0, purgeable - _shortfall(org_id, 0, replacing))


def org_headroom(org_id: int, *, bin_purge: BinPurgeGrant | None) -> tuple[int, int]:
    """(free bytes, purgeable bytes): what may still be added, and what purging the bin adds to that.

    The purgeable bytes are what is left of the bin's bytes once an overage of the quota is
    covered, and zero without a `bin_purge` grant. The same numbers as `org_free_bytes` and
    `org_writable_bytes`, from one pass over the org's files.
    """
    shortfall = _shortfall(org_id, 0)
    free_bytes = max(0, -shortfall)
    binned_bytes = StorageRecycleBinService.binned_bytes(org_id) if bin_purge is not None else 0
    return free_bytes, max(0, binned_bytes - shortfall) - free_bytes


def is_over_quota(org_id: int) -> bool:
    return org_used_bytes(org_id) > settings.ORG_STORAGE_QUOTA


def ensure_fits_quota(
    org_id: int, size: int, replacing=(), *, bin_purge: BinPurgeGrant | None
) -> None:
    """Raise 413 unless `size` more bytes fit, counting the storage bin as freeable under a
    `bin_purge` grant.

    An early reject only: record_files_within_quota decides, and purges, under the org lock.
    """
    if size > org_writable_bytes(org_id, replacing=replacing, bin_purge=bin_purge):
        raise StorageQuotaExceeded()


def record_files_within_quota(
    org_id: int,
    files: list[tuple[str, int]],
    folders=(),
    *,
    recycle_bin: StorageRecycleBinService,
    bin_purge: BinPurgeGrant | None,
    user: object | None = None,
    authors_by_path: Mapping[str, int | None] | None = None,
) -> list[PurgedBinEntry]:
    """Write rows for stored files [(path, size)] and empty folders, or raise 413 if they don't fit.

    The org row lock serializes the quota check across concurrent writers of one org.
    Under a `bin_purge` grant, files that don't fit first purge the org's oldest storage
    bin entries, just enough of them (see StorageRecycleBinService.make_room); if the whole
    bin isn't enough, nothing is purged. Without a grant they raise 413 straight away, the
    bin counted as used. `authors_by_path` overrides the author of the rows it names that get
    inserted; see `StorageFileSync.on_bulk_upload`.

    Returns:
        The bin entries purged, oldest first; empty when the files fit as they were.

    Raises:
        StorageQuotaExceeded: the files don't fit, even with the storage bin purged when
            the write may purge it.
    """
    size = sum(file_size for _, file_size in files)
    replacing = [path for path, _ in files]
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        purged = []
        shortfall = _shortfall(org_id, size, replacing)
        if shortfall > 0:
            if bin_purge is None:
                raise StorageQuotaExceeded()
            purged = recycle_bin.make_room(org_id, shortfall, actor=bin_purge.actor)
            # make_room skips an entry another purge removed after the pick, and an agent
            # write adds bytes without taking the org lock, so what make_room freed may
            # still fall short: this locked re-check is what decides.
            if _shortfall(org_id, size, replacing) > 0:
                raise StorageQuotaExceeded()
        StorageFileSync.on_bulk_upload(
            org_id, files, folders, user=user, authors_by_path=authors_by_path
        )
    return purged


def purge_bin_to_fit_quota(
    org_id: int, *, recycle_bin: StorageRecycleBinService, bin_purge: BinPurgeGrant
) -> list[PurgedBinEntry]:
    """Bring an org that already stored bytes past its quota back under it by purging its bin.

    Meant for writes that are already stored (python code writes straight to storage) and so
    cannot be rejected. Purges the org's oldest storage bin entries, just enough of them, like
    record_files_within_quota does for a write that doesn't fit, under the same org row lock.

    Returns:
        The bin entries purged, oldest first; empty when the org was not over its quota.

    Raises:
        StorageQuotaExceeded: the whole bin is not enough; nothing is purged.
    """
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org_id)
        overage = _shortfall(org_id, 0)
        if overage <= 0:
            return []
        return recycle_bin.make_room(org_id, overage, actor=bin_purge.actor)
