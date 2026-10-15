"""Remove recycle-bin items for good: one on request, or every expired one."""

from collections import Counter
from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.db import router, transaction
from django.db.models.deletion import Collector
from django.utils import timezone
from tables.exceptions import CrossOrgCascadeError
from tables.models import SourceCollection, StorageFile
from tables.models.base_models import SoftDeleteFields, SoftDeleteMixin
from tables.services.cascade_org_guard import CascadeOrgGuard
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.recycle_bin.registry import bin_resource_for, bin_resources
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from utils.logger import logger

RETENTION_JOB_ACTOR = "retention job"
_SWEEP_CHUNK_SIZE = 500


class PurgeService:
    @staticmethod
    def purge(root: SoftDeleteMixin, *, actor: str) -> None:
        """Hard-delete a binned root and everything that cascades from it.

        A collection goes through CollectionManagementService.purge_collection,
        which also drops the document content and GraphRAG data only it used.
        Callers pick `root` from RecycleBinService.binned(); this method doesn't
        apply the bin's org filter itself.

        Every purge is logged with `actor` (who asked for it, e.g. "user 7" or
        "retention job"): it can't be undone, so it must be traceable. The log
        line holds ids only, no names.

        Raises:
            NotInRecycleBinError: `root` is live (e.g. restored after the caller
                loaded it). Purge never removes a live item.
            CrossOrgCascadeError: The purge would delete or update a row of another
                organization (see CascadeOrgGuard); nothing is deleted.
        """
        resource = bin_resource_for(type(root))
        pk = root.pk
        org_id = getattr(root, f"{resource.org_field}_id")
        batch = root.soft_delete_batch

        if isinstance(root, SourceCollection):
            CollectionManagementService.purge_collection(root)
        else:
            root.purge()

        logger.info(
            "Purged {model} {pk} of org {org_id} (batch {batch}) by {actor}",
            model=resource.model.__name__,
            pk=pk,
            org_id=org_id,
            batch=batch,
            actor=actor,
        )

    @classmethod
    def purge_expired(
        cls, now: datetime | None = None, *, actor: str = RETENTION_JOB_ACTOR
    ) -> dict[str, int]:
        """Hard-delete everything that has been in the recycle bin longer than the retention time.

        Covers rows the bin page can't show too: rows binned before
        soft_delete_batch existed, built-in tools (no org), and child rows
        deleted on their own. Safe on several replicas at once: every row is
        taken with select_for_update(skip_locked=True), so a row another process
        holds (a restore, another purge) is left for the next run. One failing
        item is logged and skipped, so it can't stall the bin.

        Returns:
            Rows hard-deleted per model label, only labels above 0. A purged root
            counts once under its own label (its cascade isn't counted); a swept
            row counts with everything its delete cascaded to.
        """
        cutoff = (now or timezone.now()) - timedelta(days=settings.RECYCLE_BIN_RETENTION_DAYS)
        counts: Counter[str] = Counter()
        counts[StorageFile._meta.label] += cls._purge_expired_storage(cutoff, actor)
        root_models = {resource.model for resource in bin_resources().values()}
        for model in root_models:
            counts[model._meta.label] += cls._purge_expired_roots(model, cutoff, actor)
        # After the roots, so a root purged above takes its children with it.
        for model in cls._leftover_models(root_models):
            counts.update(cls._sweep_expired_rows(model, cutoff, root_models))
        return {label: count for label, count in counts.items() if count}

    @staticmethod
    def _purge_expired_storage(cutoff: datetime, actor: str) -> int:
        service = StorageRecycleBinService(get_storage_manager())
        expired_batches = (
            StorageFile.deleted_objects.filter(
                soft_deleted_at__lt=cutoff, soft_delete_batch__isnull=False
            )
            .values_list("org_id", "soft_delete_batch")
            .distinct()
        )
        purged = 0
        for org_id, batch in list(expired_batches):
            try:
                purged += service.purge_expired_batch(org_id, batch, cutoff, actor=actor)
            except CrossOrgCascadeError:
                # The guard logged the batch, the row it reaches and both organizations;
                # the batch stays in the bin until the link is removed.
                continue
            except Exception:
                # A background job: one failing batch mustn't stall the rest of the bin.
                logger.exception(
                    "Recycle bin purge failed for storage batch {} in org {}", batch, org_id
                )
        return purged

    @classmethod
    def _purge_expired_roots(cls, model, cutoff: datetime, actor: str) -> int:
        expired = model.deleted_objects.filter(soft_deleted_at__lt=cutoff)
        purged = 0
        for pk in list(expired.values_list("pk", flat=True)):
            try:
                with transaction.atomic():
                    # Re-check under the lock: the row may have been restored,
                    # purged by hand, or removed by an earlier cascade.
                    root = expired.select_for_update(skip_locked=True).filter(pk=pk).first()
                    if root is None:
                        continue
                    cls.purge(root, actor=actor)
                purged += 1
            except CrossOrgCascadeError:
                # The guard logged the root, the row it reaches and both organizations;
                # the root stays in the bin until the link is removed.
                continue
            except Exception:
                logger.exception("Recycle bin purge failed for {} {}", model._meta.label, pk)
        return purged

    @classmethod
    def _sweep_expired_rows(cls, model, cutoff: datetime, root_models: set) -> Counter[str]:
        """Hard-delete a leftover model's expired rows in chunks.

        A row whose batch still has a binned root anywhere is held back: its root
        was skipped (a restore holds it) or failed, and a restore must bring the
        row back with it. Like any hard delete, this cascades to rows that point
        at the swept ones. A chunk that fails is retried row by row; rows that
        still fail are logged and left out for the rest of the run, so one bad
        row can't block the model for good.

        Each row's delete must stay inside the row's own organization (see
        CascadeOrgGuard): a chunk is split by organization first and each
        organization's rows are deleted on their own. A row whose delete would
        reach another organization's row is logged once and kept in the bin; the
        rest of the model, its own organization's rows included, is still swept.
        A chunk that can't be split by organization at all is logged once and
        swept row by row too.
        """
        deleted: Counter[str] = Counter()
        expired = model.deleted_objects.filter(soft_deleted_at__lt=cutoff)
        for root_model in root_models:
            expired = expired.exclude(
                soft_delete_batch__in=root_model.deleted_objects.exclude(
                    soft_delete_batch__isnull=True
                ).values("soft_delete_batch")
            )
        failed_pks: set = set()
        using = router.db_for_write(model)
        while True:
            with transaction.atomic():
                chunk = list(
                    expired.exclude(pk__in=failed_pks)
                    .select_for_update(skip_locked=True)
                    .order_by("pk")
                    .values_list("pk", flat=True)[:_SWEEP_CHUNK_SIZE]
                )
            if not chunk:
                return deleted
            # Quiet: a refused group is retried row by row, which logs the refused row.
            try:
                groups = CascadeOrgGuard.per_org(model, chunk, using, log_refusal=False)
            except CrossOrgCascadeError:
                # A row belongs to two organizations: the row-by-row pass finds it.
                deleted.update(cls._sweep_one_by_one(model, expired, chunk, failed_pks, using))
                continue
            except Exception:
                # Row by row, so one row the split can't read doesn't stop the whole run.
                logger.exception(
                    "Recycle bin sweep could not split {} rows {} by organization; "
                    "sweeping them one by one",
                    model._meta.label,
                    chunk,
                )
                deleted.update(cls._sweep_one_by_one(model, expired, chunk, failed_pks, using))
                continue
            # One organization at a time, so a bad row only holds back its own org's rows.
            for org_guard, org_pks in groups:
                try:
                    with transaction.atomic():
                        deleted.update(cls._delete_locked(model, expired, org_guard, org_pks))
                except Exception:
                    deleted.update(
                        cls._sweep_one_by_one(model, expired, org_pks, failed_pks, using)
                    )

    @classmethod
    def _sweep_one_by_one(
        cls, model, expired, pks: list, failed_pks: set, using: str
    ) -> Counter[str]:
        """Hard-delete each row of `pks` on its own; add the ones that fail to `failed_pks`.

        A row the guard refuses is logged once, by the guard, with the row it reaches.
        """
        deleted: Counter[str] = Counter()
        for pk in pks:
            try:
                with transaction.atomic():
                    for org_guard, org_pks in CascadeOrgGuard.per_org(model, [pk], using):
                        deleted.update(cls._delete_locked(model, expired, org_guard, org_pks))
            except CrossOrgCascadeError:
                failed_pks.add(pk)
            except Exception:
                logger.exception("Recycle bin sweep failed for {} {}", model._meta.label, pk)
                failed_pks.add(pk)
        return deleted

    @staticmethod
    def _delete_locked(model, expired, org_guard: CascadeOrgGuard, pks: list) -> Counter[str]:
        """Lock the rows of `pks` still in `expired`, then hard-delete them.

        Re-checked through `expired`: a row restored and deleted again since the
        chunk was read has a new deletion time and isn't due yet. `pks` are rows of
        `org_guard`'s organization (see CascadeOrgGuard.per_org), and the delete is
        held to it.

        Raises:
            CrossOrgCascadeError: A row's delete would reach another organization's
                row; the caller's transaction must roll back.
        """
        locked = list(
            expired.filter(pk__in=pks)
            .select_for_update(skip_locked=True)
            .values_list("pk", flat=True)
        )
        if not locked:
            return Counter()
        using = org_guard.using
        # What QuerySet.delete() does, with the collected rows checked in between.
        rows = model.all_objects.using(using).filter(pk__in=locked)
        collector = Collector(using=using, origin=rows)
        collector.collect(rows)
        org_guard.check_collected(collector)
        _, per_label = collector.delete()
        return Counter(per_label)

    @staticmethod
    def _leftover_models(root_models: set) -> list:
        return [
            model
            for model in apps.get_models()
            if issubclass(model, SoftDeleteFields)
            and not model._meta.proxy
            and model is not StorageFile
            and model not in root_models
        ]
