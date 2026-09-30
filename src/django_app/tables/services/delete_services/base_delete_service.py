from abc import ABC, abstractmethod

from django.db import models, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework.exceptions import NotFound, PermissionDenied

from tables.models.base_models import SoftDeleteMixin
from tables.services.delete_services.usage import (
    BulkDeleteResult,
    SkipEntry,
    SkipReason,
    UsageReport,
)
from tables.services.rbac.effective_permissions import EffectivePermissions


class BaseDeleteService(ABC):
    """Base class for entity bulk-delete services.

    Owns the whole algorithm -- scope, usage, skip, delete -- so each entity
    declares only two things: which rows its org may delete, and what
    references them.

    Unlike BaseCopyService, which is a thin interface (one abstract method, no
    state), this is a template method: the shared part is the valuable part, so
    it needs `model` and overridable hooks. The style is still copied from
    copy_services -- absolute imports, `...` abstract bodies, one-line summaries.
    """

    @property
    @abstractmethod
    def model(self) -> type[models.Model]:
        """The entity this service deletes.

        Concrete subclasses set it as a plain class attribute; one that forgets
        cannot be instantiated.
        """

    @abstractmethod
    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """Per-id report of which visible/hidden resources reference each row.

        Must return an entry for every id passed in -- the response shape is
        uniform across entities and across rows. An entity nothing can reference
        returns empty reports rather than opting out of the contract.
        """

    def get_deletable_queryset(self, org_id: int) -> models.QuerySet:
        """Rows this org is allowed to delete.

        Deletability is not visibility: the default is ownership, and hybrid
        models must narrow rather than widen it. Globally visible rows belong
        to no org and must never be deletable through an org-scoped endpoint.
        """
        return self.model.objects.filter(org_id=org_id)

    def assert_deletable(
        self, instance: models.Model, org_id: int, effective: EffectivePermissions
    ) -> None:
        """Guard for the single-object destroy path. Call it inside a transaction.

        Runs the same rule as bulk, so a caller cannot bypass the block by
        deleting one id at a time. Like bulk, it re-reads the row through the
        deletable scope under a row lock: a row outside the scope is a 404, and
        the lock holds until the caller's delete commits in the same
        transaction.
        """
        if not self._resolve([instance.pk], org_id, lock=True):
            raise NotFound()
        report = self.collect_usage([instance.pk], org_id, effective)[instance.pk]
        if report.blocked:
            raise PermissionDenied(SkipReason.IN_USE_RESTRICTED.value)

    def bulk_delete(
        self,
        ids: list[int],
        org_id: int,
        effective: EffectivePermissions,
        dry_run: bool = False,
    ) -> BulkDeleteResult:
        """Delete every requested id this caller may delete, and report the rest."""
        ids = list(dict.fromkeys(ids))
        if dry_run:
            return self._preview(ids, org_id, effective)

        # One transaction around read-decide-write: evaluating usage outside it
        # would let a concurrent request attach the entity to something hidden
        # between the check and the delete. The row lock also covers a *new*
        # referencing row: on PostgreSQL inserting an FK takes FOR KEY SHARE on
        # the target, which waits on this FOR UPDATE and then fails once the
        # row is gone. The gap left is soft delete, where the row survives and
        # the waiting insert goes through.
        with transaction.atomic():
            found = self._resolve(ids, org_id, lock=True)
            # Every pk is read up front: Model.delete() clears it on the
            # instance, so anything derived from `found` afterwards would see
            # None. This is the one ordering constraint in the method.
            found_ids = [obj.pk for obj in found]
            usage = self.collect_usage(found_ids, org_id, effective)
            deletable, skipped = self._partition(found, usage)
            deletable_ids = [obj.pk for obj in deletable]
            deleted_ids, blocked_at_delete = self._delete_rows(deletable)

        # Usage was needed above to decide what to skip, but it is the preview
        # payload: on a real delete it adds nothing actionable -- visible
        # entities are gone, blocked ones report visible_count=0. `{}` rather
        # than dropping the key, so the response shape never varies.
        return BulkDeleteResult(
            dry_run=False,
            deletable_ids=deletable_ids,
            deleted_ids=deleted_ids,
            not_found_ids=self._not_found_ids(ids, found_ids),
            skipped=skipped + blocked_at_delete,
            usage={},
        )

    def _preview(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> BulkDeleteResult:
        """What a real call would do. Opens no transaction -- it writes nothing."""
        found = self._resolve(ids, org_id, lock=False)
        found_ids = [obj.pk for obj in found]
        usage = self.collect_usage(found_ids, org_id, effective)
        deletable, skipped = self._partition(found, usage)

        return BulkDeleteResult(
            dry_run=True,
            deletable_ids=[obj.pk for obj in deletable],
            deleted_ids=[],
            not_found_ids=self._not_found_ids(ids, found_ids),
            skipped=skipped,
            usage=usage,
        )

    def _resolve(
        self, ids: list[int], org_id: int, *, lock: bool
    ) -> list[models.Model]:
        """The requested rows this org may delete, in request order."""
        queryset = self.get_deletable_queryset(org_id).filter(pk__in=ids)
        if lock:
            # of=("self",) so a queryset that joins to reach its org (e.g.
            # GraphVersion via graph__org_id) locks only the target rows.
            # Locking in pk order means two overlapping bulk deletes wait on
            # each other instead of deadlocking.
            queryset = queryset.order_by("pk").select_for_update(of=("self",))
        by_id = {obj.pk: obj for obj in queryset}
        return [by_id[entity_id] for entity_id in ids if entity_id in by_id]

    @staticmethod
    def _not_found_ids(ids: list[int], found_ids: list[int]) -> list[int]:
        """Ids that do not exist, belong to another org, or are not deletable.

        All three collapse into one bucket on purpose: telling them apart would
        leak the existence of rows the caller cannot act on. Takes ids rather
        than instances because the instances may already have been deleted.
        """
        resolved = set(found_ids)
        return [entity_id for entity_id in ids if entity_id not in resolved]

    def _partition(
        self, found: list[models.Model], usage: dict[int, UsageReport]
    ) -> tuple[list[models.Model], list[SkipEntry]]:
        """Split found rows into those to delete and those to report as skipped."""
        deletable: list[models.Model] = []
        skipped: list[SkipEntry] = []

        for obj in found:
            if usage[obj.pk].blocked:
                skipped.append(
                    SkipEntry(id=obj.pk, reason=SkipReason.IN_USE_RESTRICTED)
                )
            else:
                deletable.append(obj)

        return deletable, skipped

    def _delete_rows(
        self, instances: list[models.Model]
    ) -> tuple[list[int], list[SkipEntry]]:
        """Remove rows that passed every check.

        Soft-delete roots MUST go row by row: SoftDeleteMixin overrides
        delete() on the *instance*, and QuerySet.delete() bypasses that
        override entirely -- a bulk delete would silently hard-delete them.
        Everything else takes the queryset path, where the cascade is collected
        once for the whole set instead of once per row.
        """
        if not instances:
            return [], []

        if issubclass(self.model, SoftDeleteMixin):
            return self._delete_one_by_one(instances)

        self.model.objects.filter(pk__in=[obj.pk for obj in instances]).delete()
        return [obj.pk for obj in instances], []

    @staticmethod
    def _delete_one_by_one(
        instances: list[models.Model],
    ) -> tuple[list[int], list[SkipEntry]]:
        """Delete each row in its own savepoint, reporting the ones refused.

        Only the row-by-row path gets partial success. The queryset path above
        cannot: a failure there rolls back the batch. That asymmetry is safe
        today because no reverse FK on the queryset-path entities uses PROTECT
        or RESTRICT, so there is nothing for those deletes to be refused by.
        Revisit this the moment a PROTECT lands on any of them.

        ImproperlyConfigured is deliberately NOT caught: it means a broken FK
        declaration, which is a bug to surface, not a row to skip.
        """
        deleted_ids: list[int] = []
        refused: list[SkipEntry] = []

        for obj in instances:
            entity_id = obj.pk  # capture before delete() clears it
            try:
                # Nested inside the caller's atomic block, so this is a
                # savepoint: one refused row does not lose the whole batch.
                with transaction.atomic():
                    obj.delete()
            except (ProtectedError, RestrictedError):
                refused.append(SkipEntry(id=entity_id, reason=SkipReason.PROTECTED))
                continue
            deleted_ids.append(entity_id)

        return deleted_ids, refused
