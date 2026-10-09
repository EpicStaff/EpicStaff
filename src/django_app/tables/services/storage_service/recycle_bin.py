"""The storage recycle bin: what it holds, restoring an item, and deleting it for good."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from rbac.models import Organization
from rest_framework.exceptions import APIException
from tables.exceptions import NotInRecycleBinError, StorageRestoreConflictError
from tables.models import StorageFile
from tables.services.recycle_bin.bin_contents_service import (
    CONTENTS_LIMIT,
    SHOW_ALL_LIMIT,
    BinContent,
    BinDetail,
)
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_results import BulkFailure, BulkPurgeResult, BulkRestoreResult
from tables.services.recycle_bin.restore_service import RestoreResult
from tables.services.storage_service.db_sync import _ancestor_paths, _name_of, _parent_of
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.naming import ensure_unique_file_name, split_file_name
from utils.logger import logger

_REACTIVATED_FIELDS = [
    "path",
    "name",
    "parent_path",
    "active",
    "soft_deleted_at",
    "soft_delete_batch",
]


# The list's sort choices. Days left falls as the deletion time gets older, so
# it sorts by that time; ties go by path, then id, so pages never overlap.
ENTRY_ORDERINGS: dict[str, tuple[str, ...]] = {
    "-deleted_at": ("-soft_deleted_at", "path", "pk"),
    "deleted_at": ("soft_deleted_at", "path", "pk"),
    "days_left": ("soft_deleted_at", "path", "pk"),
    "-days_left": ("-soft_deleted_at", "path", "pk"),
}


def _failure(row: StorageFile, error: Exception) -> BulkFailure:
    if isinstance(error, APIException):
        message = str(error.detail)
    else:
        logger.exception("Storage recycle bin bulk action failed for row {}", row.pk)
        message = "Something went wrong with this item. Try it again on its own."
    return BulkFailure(id=row.pk, name=row.path, message=message)


@dataclass(frozen=True)
class StorageRecycleBinEntry:
    id: int
    name: str  # the full org-relative path; folders end in "/"
    item_type: str
    deleted_at: datetime
    days_left: int
    details: list[BinDetail] = field(default_factory=list)
    contents: list[BinContent] = field(default_factory=list)
    contents_total: int = 0


class StorageRecycleBinService:
    def __init__(self, manager: StorageManager):
        self._manager = manager

    @staticmethod
    def binned(org_id: int) -> QuerySet:
        """The org's binned storage rows. Rows binned before batches existed are left out."""
        return StorageFile.deleted_objects.filter(org_id=org_id, soft_delete_batch__isnull=False)

    @classmethod
    def top_level(cls, org_id: int) -> QuerySet:
        """The binned rows a user acts on: those whose folder wasn't deleted with them.

        A row under a folder of its own batch comes back or goes only with that
        folder, as on a desktop's bin, so the bin neither lists nor takes it on its own.
        """
        deleted_with_its_folder = StorageFile.deleted_objects.filter(
            org_id=OuterRef("org_id"),
            soft_delete_batch=OuterRef("soft_delete_batch"),
            path=OuterRef("parent_path"),
        )
        return cls.binned(org_id).exclude(Exists(deleted_with_its_folder))

    @classmethod
    def entry_rows(
        cls, org_id: int, search: str = "", ordering: str = "-deleted_at", item_type: str = ""
    ) -> QuerySet:
        """The org's top-level binned files and folders; pass a page of it to to_entries.

        `search` matches the item's own name or, for a folder, the name of anything deleted
        with it (a file can be found without knowing its folder); `item_type` keeps only files
        or folders; `ordering` is one of ENTRY_ORDERINGS (newest first by default).
        """
        rows = cls.top_level(org_id)
        if search:
            matching_inside = StorageFile.deleted_objects.filter(
                org_id=OuterRef("org_id"),
                soft_delete_batch=OuterRef("soft_delete_batch"),
                path__startswith=OuterRef("path"),
                name__icontains=search,
            )
            rows = rows.filter(Q(name__icontains=search) | Q(Exists(matching_inside)))
        if item_type in ("file", "folder"):
            rows = rows.filter(item_type=item_type)
        return rows.order_by(
            *ENTRY_ORDERINGS.get(ordering, ENTRY_ORDERINGS["-deleted_at"])
        ).values_list(
            "pk",
            "path",
            "item_type",
            "soft_deleted_at",
            "soft_delete_batch",
            "size",
            "parent_path",
            "created_at",
            "updated_at",
        )

    @classmethod
    def to_entries(cls, org_id: int, rows) -> list[StorageRecycleBinEntry]:
        """Entries for a page of entry_rows; a folder lists what its restore brings back."""
        rows = list(rows)
        parent_paths = {row[6] for row in rows if row[6]}
        live_folders = set(
            StorageFile.objects.filter(org_id=org_id, path__in=parent_paths).values_list(
                "path", flat=True
            )
        )
        entries = []
        for (
            pk,
            path,
            item_type,
            deleted_at,
            batch,
            size,
            parent_path,
            created_at,
            updated_at,
        ) in rows:
            contents, total = (
                cls._folder_contents(path, batch) if item_type == "folder" else ([], 0)
            )
            entries.append(
                StorageRecycleBinEntry(
                    id=pk,
                    name=path,
                    item_type=item_type,
                    deleted_at=deleted_at,
                    days_left=RecycleBinService.days_left(deleted_at),
                    details=cls._details(
                        path,
                        item_type,
                        size,
                        parent_path,
                        created_at,
                        updated_at,
                        folder_is_live=not parent_path or parent_path in live_folders,
                    ),
                    contents=contents,
                    contents_total=total,
                )
            )
        return entries

    @staticmethod
    def _details(
        path, item_type, size, parent_path, created_at, updated_at, *, folder_is_live: bool
    ) -> list[BinDetail]:
        """Where the item was and when it changed; a file also has its size and type.

        Every field is sent, null when empty, so all rows of the tab line up. A
        notice follows when the item's folder is gone: a restore makes a new one.
        """
        details = [BinDetail(label="Location", value=parent_path or "/")]
        if item_type == "file":
            _, extension = split_file_name(path.rsplit("/", 1)[-1])
            details += [
                BinDetail(label="Size", value=size, format="size"),
                BinDetail(label="Type", value=extension.lstrip(".").upper() or None),
            ]
        details += [
            BinDetail(
                label="Created", value=created_at.isoformat() if created_at else None, format="date"
            ),
            BinDetail(
                label="Last changed",
                value=updated_at.isoformat() if updated_at else None,
                format="date",
            ),
        ]
        if not folder_is_live:
            details.append(
                BinDetail(
                    label="Comes back to",
                    value=f"A new {parent_path} folder: the one it was in is deleted.",
                    format="notice",
                )
            )
        return details

    @classmethod
    def contents_of(cls, org_id: int, row_id: int) -> tuple[list[BinContent], int]:
        """The rows deleted with one top-level binned folder, up to SHOW_ALL_LIMIT: the bin's "Show all".

        Raises:
            NotInRecycleBinError: the row isn't a top-level item of this org's bin.
        """
        row = cls.top_level(org_id).filter(pk=row_id).first()
        if row is None:
            raise NotInRecycleBinError()
        if row.item_type != "folder":
            return [], 0
        return cls._folder_contents(row.path, row.soft_delete_batch, limit=SHOW_ALL_LIMIT)

    @staticmethod
    def _folder_contents(
        folder_path: str, batch: uuid.UUID, limit: int | None = CONTENTS_LIMIT
    ) -> tuple[list[BinContent], int]:
        """The rows deleted with the folder, under its path (at most `limit`, None for all).

        Two queries per folder on the page.
        """
        rows = StorageFile.deleted_objects.filter(
            soft_delete_batch=batch, path__startswith=folder_path
        ).exclude(path=folder_path)
        named = rows.order_by("path").values_list("path", "item_type")
        if limit is not None:
            named = named[:limit]
        contents = [
            BinContent(name=path[len(folder_path) :], kind=item_type) for path, item_type in named
        ]
        return contents, rows.count()

    def restore_many(self, org_id: int, row_ids: list[int] | None) -> BulkRestoreResult:
        """Restore each id in order, or every binned row of the org when `row_ids` is None.

        An id an earlier folder restore already brought back is reported with
        its current path. Each id is its own transaction: its objects move in
        storage, which a later id's failure can't undo. A failing id (a restore
        conflict, say) is reported and the rest go on.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin; nothing is restored.
        """
        result = BulkRestoreResult()
        for row_id in self._target_ids(org_id, row_ids):
            row = StorageFile.all_objects.filter(org_id=org_id, pk=row_id).first()
            if row is None:
                continue  # purged meanwhile
            if row.active:
                result.restored.append(RestoreResult(object=row, renamed_from=None))
                continue
            try:
                result.restored.append(self.restore(org_id, row_id))
            except Exception as error:  # one item mustn't stop the rest; reported per item
                result.failed.append(_failure(row, error))
        return result

    def restore(self, org_id: int, row_id: int) -> RestoreResult:
        """Bring a binned file, or a binned folder with its batch's rows under it, back.

        1. A file comes back at its old path. Each parent folder is reused if
           live and otherwise created new (a folder deleted on its own stays
           whole in the bin).
        2. A folder brings back every binned row of its batch under its path,
           plus its parent folders as in rule 1. A row deleted with its folder
           isn't restored on its own (see top_level).
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
            self._restore_ancestors(org_id, final_path)
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

    def purge_many(self, org_id: int, row_ids: list[int] | None, *, actor: str) -> BulkPurgeResult:
        """Purge each id, or every binned row of the org when `row_ids` is None.

        An id an earlier folder purge already removed is skipped.

        Raises:
            NotInRecycleBinError: an id isn't in this org's bin; nothing is purged.
        """
        result = BulkPurgeResult()
        for row_id in self._target_ids(org_id, row_ids):
            row = StorageFile.deleted_objects.filter(org_id=org_id, pk=row_id).first()
            if row is None:
                continue  # went with an earlier folder, or restored meanwhile
            try:
                self.purge(org_id, row_id, actor=actor)
                result.purged.append(row_id)
            except Exception as error:  # one item mustn't stop the rest; reported per item
                result.failed.append(_failure(row, error))
        return result

    def _target_ids(self, org_id: int, row_ids: list[int] | None) -> list[int]:
        if row_ids is None:
            return list(
                self.top_level(org_id)
                .order_by("-soft_deleted_at", "path", "pk")
                .values_list("pk", flat=True)
            )
        self._check_all_binned(org_id, row_ids)
        return list(dict.fromkeys(row_ids))

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
        if self.top_level(org_id).filter(pk__in=unique_ids).count() != len(unique_ids):
            raise NotInRecycleBinError()

    def _lock_batch_of(self, org_id: int, row_id: int) -> tuple[list[StorageFile], StorageFile]:
        """Lock every binned row of `row_id`'s batch and return them with the row itself.

        The whole batch is locked in one ordered statement before the row is
        looked at, so a restore and a purge of two rows of one batch queue up
        instead of each holding one row and waiting for the other's (a deadlock).

        Raises:
            NotInRecycleBinError: the row isn't in this org's bin (any more), or
                was deleted with its folder.
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
        if any(row.path == root.parent_path for row in batch_rows):
            raise NotInRecycleBinError()  # it goes with its folder; see top_level
        return batch_rows, root

    @staticmethod
    def _free_path(org_id: int, path: str) -> str:
        siblings = StorageFile.objects.filter(
            org_id=org_id, parent_path=_parent_of(path)
        ).values_list("path", flat=True)
        return ensure_unique_file_name(path, siblings)

    @staticmethod
    def _restore_ancestors(org_id: int, path: str) -> None:
        """Make every parent folder of `path` live.

        A live folder is reused; otherwise a new folder row is made. A deleted
        one stays whole in the bin: it was deleted in another batch, since a
        row deleted with its folder isn't restored on its own.
        """
        for ancestor in _ancestor_paths(path):
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
