"""Measure the bytes an organization stores that no StorageFile row accounts for.

Run code holding temporary storage credentials writes straight to the store, so the
StorageFile index misses those bytes (and a row whose size could not be read counts 0).
The quota adds what this measurement finds as `OrganizationStorageUsage.unindexed_bytes`.

The rule: every mint of temporary credentials moves the organization's `measure_until`
deadline to at least mint time + credential TTL + a mint allowance + one measurement
interval (`request_measurement`), so at least one hourly measurement runs after the last
minted keys can no longer write. An organization is measured hourly while `measure_until`
has not passed and while `unindexed_bytes > 0`. Each measurement subtracts
min(index before listing, index after listing) from the stored bytes: an upload landing
while the store is listed errs toward an over-count, which the next hour heals. Bytes a
running execution writes through the SDK may likewise be counted twice (unindexed now,
indexed once its storage_mutations arrive after the run) until the next measurement; this
over-count is accepted.
"""

import time
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from tables.models import OrganizationStorageUsage
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.path_utils import storage_key
from tables.services.storage_service.quota import org_indexed_bytes
from utils.logger import logger

# The backend starts the key expiry when it receives the mint request, slightly after the stamp.
MINT_ALLOWANCE = timedelta(minutes=5)
MEASUREMENT_INTERVAL = timedelta(hours=1)
# Keys minted with TTL <= 0 never expire (not a production setting): measure indefinitely.
NO_EXPIRY_DEADLINE = datetime.max.replace(tzinfo=UTC)


def request_measurement(org_id: int) -> None:
    """Keep the organization measured until the keys about to be minted can no longer write.

    Never moves an existing deadline earlier.
    """
    ttl_hours = settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS
    if ttl_hours > 0:
        deadline = (
            timezone.now() + timedelta(hours=ttl_hours) + MINT_ALLOWANCE + MEASUREMENT_INTERVAL
        )
    else:
        deadline = NO_EXPIRY_DEADLINE
    OrganizationStorageUsage.objects.bulk_create(
        [OrganizationStorageUsage(org_id=org_id)], ignore_conflicts=True
    )
    OrganizationStorageUsage.objects.filter(
        Q(measure_until__isnull=True) | Q(measure_until__lt=deadline), org_id=org_id
    ).update(measure_until=deadline)


def measure_organization(org_id: int) -> None:
    """Record the organization's unindexed bytes.

    Updates the existing `OrganizationStorageUsage` row only; an organization without one
    has never minted credentials and is not measured.
    """
    started = timezone.now()
    indexed_before = org_indexed_bytes(org_id)
    stored = get_storage_backend(organization_prefix=storage_key(org_id, "")).total_size("")
    indexed_after = org_indexed_bytes(org_id)
    unindexed = max(0, stored - min(indexed_before, indexed_after))

    OrganizationStorageUsage.objects.filter(org_id=org_id).update(
        unindexed_bytes=unindexed, measured_at=started
    )


def measure_due_organizations() -> None:
    """Measure every organization within its deadline and every one with unindexed bytes."""
    org_ids = OrganizationStorageUsage.objects.filter(
        Q(measure_until__gte=timezone.now()) | Q(unindexed_bytes__gt=0)
    ).values_list("org_id", flat=True)
    for org_id in list(org_ids):
        started = time.monotonic()
        try:
            measure_organization(org_id)
            logger.info(
                "Measured storage of org_id={} in {:.1f}s", org_id, time.monotonic() - started
            )
        except Exception:
            logger.exception("Storage measurement failed for org_id={}", org_id)
