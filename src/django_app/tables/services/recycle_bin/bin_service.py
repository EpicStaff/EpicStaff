"""What an organization's recycle bin holds, and how long each item has left."""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone
from tables.services.recycle_bin.registry import BinResource

_SECONDS_PER_DAY = 86400

# The list's sort choices, as storage's (storage_service.recycle_bin.ENTRY_ORDERINGS).
# Days left falls as the deletion time gets older, so it sorts by that time; ties go
# by id, so pages never overlap.
ENTRY_ORDERINGS: dict[str, tuple[str, ...]] = {
    "-deleted_at": ("-soft_deleted_at", "-pk"),
    "deleted_at": ("soft_deleted_at", "pk"),
    "days_left": ("soft_deleted_at", "pk"),
    "-days_left": ("-soft_deleted_at", "-pk"),
}
DEFAULT_ENTRY_ORDERING = "-deleted_at"


@dataclass(frozen=True)
class RecycleBinEntry:
    id: int
    name: str
    deleted_at: datetime
    days_left: int
    batch: uuid.UUID


class RecycleBinService:
    @staticmethod
    def binned(resource: BinResource, org_id: int) -> QuerySet:
        """Return the rows of `resource` that are bin entries of their own in `org_id`.

        List, restore and purge all start from this queryset, so a row the list
        hides is a 404 on restore and purge too. Left out: rows of another org
        (built-in tools have no org, so they never match) and rows binned before
        soft_delete_batch existed (restore can't tell their batch apart). A
        surface deleted with its agent is listed too: restoring it on its own
        brings it back as a shared surface (RestoreService).
        """
        return resource.model.deleted_objects.filter(
            soft_delete_batch__isnull=False,
            **{f"{resource.org_field}_id": org_id},
        )

    @staticmethod
    def entry_rows(
        resource: BinResource,
        binned: QuerySet,
        *,
        search: str = "",
        ordering: str = DEFAULT_ENTRY_ORDERING,
    ) -> QuerySet:
        """The list's rows of `binned` (a queryset from binned()); pass a page of it to to_entries.

        `search` keeps the rows whose name contains it, in any case; `ordering` is one of
        ENTRY_ORDERINGS, the default for anything else.
        """
        if search:
            binned = binned.filter(**{f"{resource.name_field}__icontains": search})
        # values_list: a flow row carries large metadata JSON the list never shows.
        return binned.order_by(
            *ENTRY_ORDERINGS.get(ordering, ENTRY_ORDERINGS[DEFAULT_ENTRY_ORDERING])
        ).values_list("pk", resource.name_field, "soft_deleted_at", "soft_delete_batch")

    @classmethod
    def to_entries(cls, rows) -> list[RecycleBinEntry]:
        """Entries for rows of entry_rows, in their order."""
        return [
            RecycleBinEntry(
                id=pk,
                name=name,
                deleted_at=deleted_at,
                days_left=cls.days_left(deleted_at),
                batch=batch,
            )
            for pk, name, deleted_at, batch in rows
        ]

    @staticmethod
    def days_left(deleted_at: datetime) -> int:
        """Whole days, rounded up, until the purge job may remove the item. 0 once due."""
        retention_seconds = settings.RECYCLE_BIN_RETENTION_DAYS * _SECONDS_PER_DAY
        remaining_seconds = retention_seconds - (timezone.now() - deleted_at).total_seconds()
        return max(0, math.ceil(remaining_seconds / _SECONDS_PER_DAY))
