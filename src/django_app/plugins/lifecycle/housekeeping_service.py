"""The plugin platform's hourly housekeeping: rows nothing reads any more.

- Ownership tombstones: a resource's delete leaves its ownership row behind (no delete
  listener may slow an ownable model's cascades), so the rows whose resource is gone are
  removed, one anti-join per ownable model, in batches.
- Revoked service-account keys, `REVOKED_KEY_RETENTION_DAYS` after their revocation. A
  revoked key never authenticates; the row only says when it stopped.
- Install and upgrade jobs whose grant was deleted while they were open fail. An
  organization removed job has no grant by design once its organization is deleted, and
  keeps running.

Like the retention tick, it runs whatever `PLUGINS_ENABLED` says, on any number of hosts.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef
from django.utils import timezone

from plugins.audit import log_retention_tick
from plugins.models import (
    HookJobKind,
    HookJobState,
    PluginHookJob,
    PluginOwnedResource,
    PluginServiceAccountKey,
)
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES
from plugins.ownership.ownership_recorder import ownable_models

REVOKED_KEY_RETENTION_DAYS = 30
HOUSEKEEPING_BATCH_SIZE = 1000
GRANT_DELETED_BEFORE_HOOK_FINISHED = "The grant was deleted before the hook finished."
# The kinds whose job is a step of its grant: without the grant it can never run.
_GRANT_STEP_KINDS = (HookJobKind.INSTALL, HookJobKind.UPGRADE)


@dataclass
class HousekeepingReport:
    tombstones_removed: int = 0
    revoked_keys_removed: int = 0
    orphaned_hook_jobs_failed: int = 0


class HousekeepingService:
    def run(self, now: datetime | None = None) -> HousekeepingReport:
        """Remove tombstones and old revoked keys, and fail grant-step jobs without a grant."""
        now = now or timezone.now()
        report = HousekeepingReport(
            tombstones_removed=self._remove_tombstones(),
            revoked_keys_removed=self._remove_revoked_keys(now),
            orphaned_hook_jobs_failed=self._fail_orphaned_hook_jobs(now),
        )
        log_retention_tick(asdict(report))
        return report

    @staticmethod
    def _remove_tombstones() -> int:
        removed = 0
        for model, content_type in ContentType.objects.get_for_models(*ownable_models()).items():
            # The base manager sees binned rows, which still exist.
            tombstones = PluginOwnedResource.objects.filter(content_type=content_type).exclude(
                Exists(model._base_manager.filter(pk=OuterRef("object_id")))
            )
            removed += _delete_in_batches(tombstones)
        return removed

    @staticmethod
    def _remove_revoked_keys(now: datetime) -> int:
        expired = PluginServiceAccountKey.objects.filter(
            revoked_at__lt=now - timedelta(days=REVOKED_KEY_RETENTION_DAYS)
        )
        return _delete_in_batches(expired)

    @staticmethod
    def _fail_orphaned_hook_jobs(now: datetime) -> int:
        return PluginHookJob.objects.filter(
            grant__isnull=True, kind__in=_GRANT_STEP_KINDS, state__in=OPEN_HOOK_JOB_STATES
        ).update(
            state=HookJobState.FAILED,
            finished_at=now,
            error=GRANT_DELETED_BEFORE_HOOK_FINISHED,
            updated_at=now,
        )


def _delete_in_batches(rows) -> int:
    """Delete the rows `rows` matches, `HOUSEKEEPING_BATCH_SIZE` at a time; returns how many."""
    deleted = 0
    while batch := list(rows.order_by("pk").values_list("pk", flat=True)[:HOUSEKEEPING_BATCH_SIZE]):
        rows.model.objects.filter(pk__in=batch).delete()
        deleted += len(batch)
    return deleted
