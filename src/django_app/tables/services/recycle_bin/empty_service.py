"""Empty an organization's whole recycle bin: every type the caller may delete, a slice per request."""

import time
from dataclasses import dataclass, field

from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_results import BulkFailure, BulkPurgeResult
from tables.services.recycle_bin.bulk_service import RecycleBinBulkService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService

STORAGE_SOURCE = "storage"
#: The order the bin's tabs show them. Must name every bin (a test checks it against the registry).
EMPTY_ORDER = (
    "flow",
    "agent",
    "surface",
    "python_tool",
    "mcp_tool",
    STORAGE_SOURCE,
    "collection",
    "key_value_table",
    "secret",
    "realtime_channel",
    "webhook_trigger",
)
#: How long one request purges for, well inside a proxy's timeout; the client calls again
#: while items remain. Each item commits on its own, so a cut-off call loses nothing.
EMPTY_TIME_BUDGET_SECONDS = 20


@dataclass(frozen=True)
class SourcedFailure:
    """An item the purge skipped, and which bin it was in."""

    source: str
    failure: BulkFailure


@dataclass
class EmptyBinResult:
    purged_count: int = 0
    failed: list[SourcedFailure] = field(default_factory=list)
    #: Items still in those bins: left for the next call, or failed ones.
    remaining: int = 0


class RecycleBinEmptyService:
    """Each item is its own transaction, so one failing item doesn't stop or undo the others."""

    @staticmethod
    def purgeable_sources(effective: EffectivePermissions) -> list[str]:
        """The bins the caller may empty: READ and DELETE on the type, the tabs the bin page shows."""
        resources = bin_resources()
        sources = []
        for source in EMPTY_ORDER:
            resource_type = (
                ResourceType.FILES if source == STORAGE_SOURCE else resources[source].resource_type
            )
            if effective.can(resource_type.value, Permission.READ) and effective.can(
                resource_type.value, Permission.DELETE
            ):
                sources.append(source)
        return sources

    @classmethod
    def empty(cls, *, org_id: int, sources: list[str], actor: str) -> EmptyBinResult:
        """Delete for good the items of `sources` in the org's recycle bin, for up to the budget.

        Stops once EMPTY_TIME_BUDGET_SECONDS have passed, after at least one item, and
        reports how many remain; calling again goes on from there.
        """
        result = EmptyBinResult()
        resources = bin_resources()
        until = time.monotonic() + EMPTY_TIME_BUDGET_SECONDS
        for source in sources:
            done_something = result.purged_count or result.failed
            if done_something and time.monotonic() >= until:
                break
            if source == STORAGE_SOURCE:
                purged = cls._empty_storage(org_id, actor, until)
            else:
                purged = RecycleBinBulkService.purge_many(
                    resources[source], org_id, None, actor=actor, until=until
                )
            result.purged_count += len(purged.purged)
            result.failed.extend(SourcedFailure(source, failure) for failure in purged.failed)
        result.remaining = cls._remaining(org_id, sources, resources)
        return result

    @staticmethod
    def _empty_storage(org_id: int, actor: str, until: float) -> BulkPurgeResult:
        return StorageRecycleBinService(get_storage_manager()).purge_many(
            org_id, None, actor=actor, until=until
        )

    @staticmethod
    def _remaining(org_id: int, sources: list[str], resources) -> int:
        """The items still in `sources`' bins, counted as the bin lists them."""
        return sum(
            StorageRecycleBinService.top_level(org_id).count()
            if source == STORAGE_SOURCE
            else RecycleBinService.binned(resources[source], org_id).count()
            for source in sources
        )
