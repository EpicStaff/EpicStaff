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

    @classmethod
    def entries(cls, resource: BinResource, org_id: int) -> list[RecycleBinEntry]:
        """Return the org's bin entries for `resource`, newest first."""
        # values_list: a flow row carries large metadata JSON the list never shows.
        rows = (
            cls.binned(resource, org_id)
            .order_by("-soft_deleted_at", "-pk")
            .values_list("pk", resource.name_field, "soft_deleted_at", "soft_delete_batch")
        )
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
