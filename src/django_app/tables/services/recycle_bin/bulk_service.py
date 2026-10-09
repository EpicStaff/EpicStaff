"""Restore or purge several recycle-bin items at once: selected ones, or a whole bin."""

from rest_framework.exceptions import APIException
from tables.exceptions import NotInRecycleBinError
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_results import BulkFailure, BulkPurgeResult, BulkRestoreResult
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import BinResource
from tables.services.recycle_bin.restore_service import RestoreService
from utils.logger import logger

_UNEXPECTED_FAILURE = "Something went wrong with this item. Try it again on its own."


class RecycleBinBulkService:
    """Each item is its own transaction, so one failing item doesn't undo or stop the others."""

    @classmethod
    def restore_many(
        cls, resource: BinResource, org_id: int, ids: list[int] | None
    ) -> BulkRestoreResult:
        """Restore `ids` in order, or every item of the org's bin when `ids` is None.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin; nothing is restored.
        """
        result = BulkRestoreResult()
        for root in cls._roots(resource, org_id, ids):
            try:
                result.restored.append(RestoreService.restore(root))
            except Exception as error:  # one item mustn't stop the rest; reported per item
                result.failed.append(cls._failure(resource, root, error))
        return result

    @classmethod
    def purge_many(
        cls, resource: BinResource, org_id: int, ids: list[int] | None, *, actor: str
    ) -> BulkPurgeResult:
        """Delete `ids` for good, or every item of the org's bin when `ids` is None.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin; nothing is purged.
        """
        result = BulkPurgeResult()
        for root in cls._roots(resource, org_id, ids):
            pk = root.pk
            try:
                PurgeService.purge(root, actor=actor)
                result.purged.append(pk)
            except Exception as error:  # one item mustn't stop the rest; reported per item
                result.failed.append(cls._failure(resource, root, error, pk=pk))
        return result

    @staticmethod
    def _roots(resource: BinResource, org_id: int, ids: list[int] | None):
        """The binned rows to act on, re-read one by one: an earlier item may have taken a later one along."""
        binned = RecycleBinService.binned(resource, org_id)
        if ids is None:
            target_ids = list(
                binned.order_by("-soft_deleted_at", "-pk").values_list("pk", flat=True)
            )
        else:
            target_ids = list(dict.fromkeys(ids))
            if binned.filter(pk__in=target_ids).count() != len(target_ids):
                raise NotInRecycleBinError()
        for pk in target_ids:
            root = binned.filter(pk=pk).first()
            if root is not None:
                yield root

    @staticmethod
    def _failure(
        resource: BinResource, root, error: Exception, pk: int | None = None
    ) -> BulkFailure:
        if isinstance(error, APIException):
            message = str(error.detail)
        else:
            logger.exception(
                "Recycle bin bulk action failed for {} {}", resource.model.__name__, root.pk
            )
            message = _UNEXPECTED_FAILURE
        return BulkFailure(
            id=pk or root.pk, name=getattr(root, resource.name_field), message=message
        )
