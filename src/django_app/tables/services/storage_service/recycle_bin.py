"""The storage recycle bin: what it holds, restoring an item, and deleting it for good."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import QuerySet
from rbac.models import Organization
from tables.exceptions import NotInRecycleBinError, StorageRestoreConflictError
from tables.models import StorageFile
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.restore_service import RestoreResult
from tables.services.storage_service.db_sync import _ancestor_paths, _name_of, _parent_of
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.naming import ensure_unique_file_name
from utils.logger import logger

_REACTIVATED_FIELDS = [
    "path",
    "name",
    "parent_path",
    "active",
    "soft_deleted_at",
    "soft_delete_batch",
]


@dataclass(frozen=True)
class StorageRecycleBinEntry:
    id: int
    name: str  # the full org-relative path; folders end in "/"
    item_type: str
    deleted_at: datetime
    days_left: int


class StorageRecycleBinService:
    def __init__(self, manager: StorageManager):
        self._manager = manager

    @staticmethod
    def binned(org_id: int) -> QuerySet:
        """The org's binned storage rows. Rows binned before batches existed are left out."""
        return StorageFile.deleted_objects.filter(org_id=org_id, soft_delete_batch__isnull=False)

    @classmethod
    def entry_rows(cls, org_id: int) -> QuerySet:
        """Every binned file and folder of the org, newest first, flat; pass a page of it to to_entries."""
        return (
            cls.binned(org_id)
            .order_by("-soft_deleted_at", "path", "pk")
            .values_list("pk", "path", "item_type", "soft_deleted_at")
        )

    @staticmethod
    def to_entries(rows) -> list[StorageRecycleBinEntry]:
        return [
            StorageRecycleBinEntry(
                id=pk,
                name=path,
                item_type=item_type,
                deleted_at=deleted_at,
                days_left=RecycleBinService.days_left(deleted_at),
            )
            for pk, path, item_type, deleted_at in rows
        ]

    def restore_many(self, org_id: int, row_ids: list[int]) -> list[RestoreResult]:
        """Restore each id in order; nothing changes when any id isn't in the org's bin.

        An id an earlier folder restore already brought back is reported with
        its current path. Each id is its own transaction: its objects move in
        storage, which a later id's failure can't undo.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin.
        """
        self._check_all_binned(org_id, row_ids)
        results = []
        for row_id in row_ids:
            row = StorageFile.all_objects.filter(org_id=org_id, pk=row_id).first()
            if row is not None and row.active:
                results.append(RestoreResult(object=row, renamed_from=None))
            else:
                results.append(self.restore(org_id, row_id))
        return results

    def restore(self, org_id: int, row_id: int) -> RestoreResult:
        """Bring a binned file, or a binned folder with its batch's rows under it, back.

        1. A file comes back at its old path. Each parent folder is reused if
           live, brought back if it was deleted in the same batch, and otherwise
           created new (a folder deleted on its own stays whole in the bin). The
           file's binned siblings stay in the bin.
        2. A folder brings back every binned row of its batch under its path,
           plus its parent folders as in rule 1.
        3. If a live item already has the name in its parent folder (a file
           "docs" and a folder "docs/" clash too), the item gets the next "#N"
           name and a folder's contents move with it. Parent folders never
           rename: a live folder at that path is reused.
        4. The objects move from the trash to the final path. A batch left with
           no binned rows left has its trash prefix deleted.

        Raises:
            NotInRecycleBinError: `row_id` isn't in this org's bin.
            StorageRestoreConflictError: an unindexed object already sits at the target path.
        """
        with transaction.atomic():
            # The org row lock uploads and quota writes take: a restore runs alone
            # among them and other restores, so the free name it picks stays free
            # and no upload overwrites what it moves back.
            Organization.objects.select_for_update().get(pk=org_id)
            batch_rows, root = self._lock_batch_of(org_id, row_id)
            batch = root.soft_delete_batch
            old_path = root.path
            rows = (
                [row for row in batch_rows if row.path.startswith(old_path)]
                if root.item_type == "folder"
                else [root]
            )

            final_path = self._free_path(org_id, old_path)
            self._restore_ancestors(org_id, final_path, batch_rows)
            self._reactivate(rows, old_root=old_path, new_root=final_path)
            try:
                self._manager.move_from_trash(org_id, batch, old_path, final_path)
            except FileExistsError as error:
                logger.warning(
                    "Storage restore of {} in org {} blocked by an unindexed object; run backfill_storage_files",
                    final_path,
                    org_id,
                )
                raise StorageRestoreConflictError(final_path) from error
            self._drop_trash_if_empty(org_id, batch)
            root.refresh_from_db()

        logger.info(
            "Restored storage {} {} of org {} (batch {})", root.item_type, root.pk, org_id, batch
        )
        return RestoreResult(object=root, renamed_from=old_path if final_path != old_path else None)

    def purge_many(self, org_id: int, row_ids: list[int], *, actor: str) -> None:
        """Purge each id; nothing changes when any id isn't in the org's bin.

        An id an earlier folder purge already removed is skipped.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin.
        """
        self._check_all_binned(org_id, row_ids)
        for row_id in row_ids:
            if StorageFile.all_objects.filter(org_id=org_id, pk=row_id).exists():
                self.purge(org_id, row_id, actor=actor)

    def purge(self, org_id: int, row_id: int, *, actor: str) -> None:
        """Delete a binned file, or a binned folder with its batch's rows under it, for good.

        Rows go first and objects second, inside the transaction: if storage
        fails the rows come back and the purge can be retried. Logged with
        `actor`, since it can't be undone.

        Raises:
            NotInRecycleBinError: `row_id` isn't in this org's bin.
        """
        with transaction.atomic():
            batch_rows, root = self._lock_batch_of(org_id, row_id)
            batch = root.soft_delete_batch
            doomed = (
                [row.pk for row in batch_rows if row.path.startswith(root.path)]
                if root.item_type == "folder"
                else [root.pk]
            )
            StorageFile.all_objects.filter(pk__in=doomed).delete()
            if len(doomed) == len(batch_rows):
                self._manager.delete_trash_batch(org_id, batch)
            else:
                self._manager.delete_trash_path(org_id, batch, root.path)

        logger.info(
            "Purged storage {item_type} {pk} of org {org_id} (batch {batch}, {count} rows) by {actor}",
            item_type=root.item_type,
            pk=row_id,
            org_id=org_id,
            batch=batch,
            count=len(doomed),
            actor=actor,
        )

    def purge_expired_batch(
        self, org_id: int, batch: uuid.UUID, cutoff: datetime, *, actor: str
    ) -> int:
        """Purge a whole batch binned before `cutoff`. Returns the rows purged, 0 if any row is locked."""
        with transaction.atomic():
            batch_rows = StorageFile.deleted_objects.filter(org_id=org_id, soft_delete_batch=batch)
            locked = list(
                batch_rows.select_for_update(skip_locked=True)
                .filter(soft_deleted_at__lt=cutoff)
                .values_list("pk", flat=True)
            )
            # All rows of a batch share soft_deleted_at, so a shorter list means a
            # restore or a user purge holds some of them. Skip; retry next run.
            if not locked or len(locked) != batch_rows.count():
                return 0
            StorageFile.all_objects.filter(pk__in=locked).delete()
            self._manager.delete_trash_batch(org_id, batch)

        logger.info(
            "Purged storage batch {batch} of org {org_id} ({count} rows) by {actor}",
            batch=batch,
            org_id=org_id,
            count=len(locked),
            actor=actor,
        )
        return len(locked)

    def _check_all_binned(self, org_id: int, row_ids: list[int]) -> None:
        unique_ids = set(row_ids)
        if self.binned(org_id).filter(pk__in=unique_ids).count() != len(unique_ids):
            raise NotInRecycleBinError()

    def _lock_batch_of(self, org_id: int, row_id: int) -> tuple[list[StorageFile], StorageFile]:
        """Lock every binned row of `row_id`'s batch and return them with the row itself.

        The whole batch is locked in one ordered statement before the row is
        looked at, so a restore and a purge of two rows of one batch queue up
        instead of each holding one row and waiting for the other's (a deadlock).

        Raises:
            NotInRecycleBinError: the row isn't in this org's bin (any more).
        """
        batch = (
            self.binned(org_id)
            .filter(pk=row_id)
            .values_list("soft_delete_batch", flat=True)
            .first()
        )
        if batch is None:
            raise NotInRecycleBinError()
        batch_rows = list(
            StorageFile.deleted_objects.select_for_update()
            .filter(org_id=org_id, soft_delete_batch=batch)
            .order_by("path")
        )
        root = next((row for row in batch_rows if row.pk == row_id), None)
        if root is None:  # restored or purged while we waited for the locks
            raise NotInRecycleBinError()
        return batch_rows, root

    @staticmethod
    def _free_path(org_id: int, path: str) -> str:
        siblings = StorageFile.objects.filter(
            org_id=org_id, parent_path=_parent_of(path)
        ).values_list("path", flat=True)
        return ensure_unique_file_name(path, siblings)

    @staticmethod
    def _restore_ancestors(org_id: int, path: str, batch_rows: list[StorageFile]) -> None:
        """Make every parent folder of `path` live.

        A live folder is reused. One deleted in the same batch (the user deleted
        the folder and restores something from it) comes back. Otherwise a new
        folder row is made: a folder deleted on its own stays whole in the bin.
        """
        binned_in_batch = {row.path: row for row in batch_rows}
        for ancestor in _ancestor_paths(path):
            if StorageFile.objects.filter(org_id=org_id, path=ancestor).exists():
                continue
            same_batch = binned_in_batch.get(ancestor)
            if same_batch is not None:
                StorageFile.all_objects.filter(pk=same_batch.pk).update(
                    active=True, soft_deleted_at=None, soft_delete_batch=None
                )
                continue
            StorageFile.objects.get_or_create(
                org_id=org_id,
                path=ancestor,
                defaults={
                    "name": _name_of(ancestor),
                    "item_type": "folder",
                    "parent_path": _parent_of(ancestor),
                },
            )

    @staticmethod
    def _reactivate(rows: list[StorageFile], old_root: str, new_root: str) -> None:
        for row in rows:
            if new_root != old_root:
                row.path = new_root + row.path[len(old_root) :]
                row.name = _name_of(row.path)
                row.parent_path = _parent_of(row.path)
            row.active = True
            row.soft_deleted_at = None
            row.soft_delete_batch = None
        StorageFile.all_objects.bulk_update(rows, _REACTIVATED_FIELDS, batch_size=1000)

    def _drop_trash_if_empty(self, org_id: int, batch: uuid.UUID) -> None:
        if not StorageFile.deleted_objects.filter(org_id=org_id, soft_delete_batch=batch).exists():
            self._manager.delete_trash_batch(org_id, batch)
