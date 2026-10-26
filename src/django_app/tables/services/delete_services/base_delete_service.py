from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.db import models, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from rbac.access.effective import EffectivePermissions
from rbac.models import LastEditTrackedModel
from rest_framework.exceptions import NotFound
from tables.exceptions import InUseRestrictedError
from tables.models.base_models import SoftDeleteMixin
from tables.services.delete_services.usage import (
    BulkDeleteResult,
    SkipEntry,
    SkipReason,
    UsageReport,
)
from tables.services.recycle_bin.deleting import move_to_recycle_bin


@dataclass(frozen=True)
class _DeletePlan:
    found_ids: list[int]
    deletable: list[models.Model]
    skipped: list[SkipEntry]
    usage: dict[int, UsageReport]


class BaseDeleteService(ABC):
    """Deletes one entity's rows for an org, skipping rows used where the caller cannot see.

    Subclasses set `model` and implement `collect_usage`.
    """

    def __init__(self, *, org_id: int, permissions: EffectivePermissions, user) -> None:
        """Bind the service to one caller.

        Args:
            user: Recorded as who deleted each row that lands in the recycle bin.
        """
        self.org_id = org_id
        self.permissions = permissions
        self.user = user

    @property
    @abstractmethod
    def model(self) -> type[models.Model]:
        """The entity this service deletes; subclasses set it as a class attribute."""

    @abstractmethod
    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Return a usage report for every id passed in, empty when nothing references it."""

    def get_deletable_queryset(self) -> models.QuerySet:
        """Rows the active org owns; globally visible rows are never deletable here."""
        return self.model.objects.filter(org_id=self.org_id)

    def assert_deletable(self, instance: models.Model) -> None:
        """Apply the bulk rule to a single DELETE. Call inside the deleting transaction.

        Locks the row, so the usage checked still holds when the caller deletes it.

        Raises:
            NotFound: The row is outside the deletable scope.
            InUseRestrictedError: Something the caller cannot see references the row.
        """
        if not self._resolve([instance.pk], lock=True):
            raise NotFound()
        if self.collect_usage([instance.pk])[instance.pk].blocked:
            raise InUseRestrictedError()

    def preview(self, ids: list[int]) -> BulkDeleteResult:
        """Report what `delete` would do with these ids, without locking or writing."""
        ids = list(dict.fromkeys(ids))
        plan = self._plan(ids, lock=False)
        return BulkDeleteResult(
            dry_run=True,
            deletable_ids=[obj.pk for obj in plan.deletable],
            deleted_ids=[],
            not_found_ids=self._not_found_ids(ids, plan.found_ids),
            skipped=plan.skipped,
            usage=plan.usage,
        )

    def delete(self, ids: list[int]) -> BulkDeleteResult:
        """Delete every requested id the caller may delete, and report the rest.

        Usage is checked and acted on in one transaction under row locks, so a new
        reference waits for the delete instead of slipping in between (a soft-deleted
        row survives, so a waiting reference to it still goes through).

        Raises:
            CrossOrgCascadeError: A soft delete would reach another organization's
                rows. The whole request rolls back (409).
        """
        ids = list(dict.fromkeys(ids))
        with transaction.atomic():
            plan = self._plan(ids, lock=True)
            # Read before deleting: Model.delete() clears pk on the instance.
            deletable_ids = [obj.pk for obj in plan.deletable]
            deleted_ids, refused = self._delete_rows(plan.deletable)

        # Usage only explains a preview; `{}` keeps the response shape fixed.
        return BulkDeleteResult(
            dry_run=False,
            deletable_ids=deletable_ids,
            deleted_ids=deleted_ids,
            not_found_ids=self._not_found_ids(ids, plan.found_ids),
            skipped=plan.skipped + refused,
            usage={},
        )

    def _plan(self, ids: list[int], *, lock: bool) -> _DeletePlan:
        found = self._resolve(ids, lock=lock)
        found_ids = [obj.pk for obj in found]
        usage = self.collect_usage(found_ids)
        deletable: list[models.Model] = []
        skipped: list[SkipEntry] = []
        for obj in found:
            if usage[obj.pk].blocked:
                skipped.append(SkipEntry(id=obj.pk, reason=SkipReason.IN_USE_RESTRICTED))
            else:
                deletable.append(obj)
        return _DeletePlan(found_ids=found_ids, deletable=deletable, skipped=skipped, usage=usage)

    def _resolve(self, ids: list[int], *, lock: bool) -> list[models.Model]:
        """The requested rows this org may delete, in request order."""
        queryset = self.get_deletable_queryset().filter(pk__in=ids)
        if lock:
            # of=("self",) locks only the target rows when the scope joins to reach
            # its org; pk order makes overlapping bulk deletes wait, not deadlock.
            queryset = queryset.order_by("pk").select_for_update(of=("self",))
        by_id = {obj.pk: obj for obj in queryset}
        return [by_id[entity_id] for entity_id in ids if entity_id in by_id]

    @staticmethod
    def _not_found_ids(ids: list[int], found_ids: list[int]) -> list[int]:
        """Ids that are missing, in another org, or not deletable.

        Collapsed on purpose: telling them apart would leak rows the caller cannot act on.
        """
        resolved = set(found_ids)
        return [entity_id for entity_id in ids if entity_id not in resolved]

    def _delete_rows(self, instances: list[models.Model]) -> tuple[list[int], list[SkipEntry]]:
        """Delete rows that passed every check; return deleted ids and refused rows.

        Soft-delete roots go row by row: QuerySet.delete() bypasses
        SoftDeleteMixin.delete and would hard-delete them.
        """
        if not instances:
            return [], []

        if issubclass(self.model, SoftDeleteMixin):
            return self._delete_one_by_one(instances)

        # No reverse FK on these entities uses PROTECT or RESTRICT, so the batch
        # cannot be refused; add per-row handling if one ever does.
        self.model.objects.filter(pk__in=[obj.pk for obj in instances]).delete()
        return [obj.pk for obj in instances], []

    def _delete_one_by_one(
        self, instances: list[models.Model]
    ) -> tuple[list[int], list[SkipEntry]]:
        deleted_ids: list[int] = []
        refused: list[SkipEntry] = []

        for obj in instances:
            entity_id = obj.pk
            try:
                # A savepoint per row: one refused row does not roll back the batch.
                with transaction.atomic():
                    if isinstance(obj, LastEditTrackedModel):
                        move_to_recycle_bin(obj, self.user)
                    else:
                        obj.delete()
            except (ProtectedError, RestrictedError):
                refused.append(SkipEntry(id=entity_id, reason=SkipReason.PROTECTED))
                continue
            deleted_ids.append(entity_id)

        return deleted_ids, refused
