"""Empty an organization's whole recycle bin: every type, a slice per request."""

import time
from dataclasses import dataclass, field

from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_results import BulkFailure, BulkPurgeResult
from tables.services.recycle_bin.bulk_service import RecycleBinBulkService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService

#: The order the bin's tabs show them. Must name every bin (a test checks it against the registry).
EMPTY_ORDER = (
    RecycleBinSource.FLOW,
    RecycleBinSource.AGENT,
    RecycleBinSource.SURFACE,
    RecycleBinSource.PYTHON_TOOL,
    RecycleBinSource.MCP_TOOL,
    RecycleBinSource.STORAGE,
    RecycleBinSource.COLLECTION,
    RecycleBinSource.KEY_VALUE_TABLE,
    RecycleBinSource.SECRET,
    RecycleBinSource.REALTIME_CHANNEL,
    RecycleBinSource.WEBHOOK_TRIGGER,
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
    #: Items still in the bins: left for the next call, or failed ones.
    remaining: int = 0


class RecycleBinEmptyService:
    """Each item is its own transaction, so one failing item doesn't stop or undo the others."""

    @classmethod
    def empty(cls, *, org_id: int, actor: str) -> EmptyBinResult:
        """Delete for good the items of every bin of the org, in EMPTY_ORDER, for up to the budget.

        Stops once EMPTY_TIME_BUDGET_SECONDS have passed, after at least one item, and
        reports how many remain; calling again goes on from there. Checks no permission:
        the caller has authorized the purge and resolved `org_id` from the active org.
        """
        result = EmptyBinResult()
        resources = bin_resources()
        until = time.monotonic() + EMPTY_TIME_BUDGET_SECONDS
        for source in EMPTY_ORDER:
            done_something = result.purged_count or result.failed
            if done_something and time.monotonic() >= until:
                break
            if source == RecycleBinSource.STORAGE:
                purged = cls._empty_storage(org_id, actor, until)
            else:
                purged = RecycleBinBulkService.purge_many(
                    resources[source], org_id, None, actor=actor, until=until
                )
            result.purged_count += len(purged.purged)
            result.failed.extend(SourcedFailure(source, failure) for failure in purged.failed)
        result.remaining = cls._remaining(org_id, resources)
        return result

    @staticmethod
    def _empty_storage(org_id: int, actor: str, until: float) -> BulkPurgeResult:
        return StorageRecycleBinService(get_storage_manager()).purge_many(
            org_id, None, actor=actor, until=until
        )

    @staticmethod
    def _remaining(org_id: int, resources) -> int:
        """The items still in the org's bins, counted as the bin lists them."""
        return sum(
            StorageRecycleBinService.top_level(org_id).count()
            if source == RecycleBinSource.STORAGE
            else RecycleBinService.binned(resources[source], org_id).count()
            for source in EMPTY_ORDER
        )
