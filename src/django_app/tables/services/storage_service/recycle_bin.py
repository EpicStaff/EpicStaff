"""The storage recycle bin: what it holds, restoring an item, and deleting it for good."""

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import router, transaction
from django.db.models import (
    BigIntegerField,
    Case,
    Exists,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    When,
)
from django.db.models.deletion import Collector
from django.db.models.functions import Coalesce
from rbac.models import Organization
from rest_framework.exceptions import APIException
from tables.exceptions import (
    CrossOrgCascadeError,
    NotInRecycleBinError,
    StorageQuotaExceeded,
    StorageRestoreConflictError,
)
from tables.models import StorageFile
from tables.services.cascade_org_guard import CascadeOrgGuard
from tables.services.recycle_bin.authorship import BinEntryAuthorship, authorship_details
from tables.services.recycle_bin.bin_contents_service import CONTENTS_LIMIT, SHOW_ALL_LIMIT
from tables.services.recycle_bin.bin_service import RecycleBinService
from tables.services.recycle_bin.bulk_results import BulkFailure, BulkPurgeResult, BulkRestoreResult
from tables.services.recycle_bin.presentation import BinContent, BinDetail, HiddenContents
from tables.services.recycle_bin.restore_service import RestoreResult
from tables.services.storage_service.dataclasses import PurgedBinEntry
from tables.services.storage_service.db_sync import _ancestor_paths, _name_of, _parent_of
from tables.services.storage_service.naming import ensure_unique_file_name, split_file_name
from utils.logger import logger

if TYPE_CHECKING:
    # Only a type here: the manager imports the quota module, which imports this one.
    from tables.services.storage_service.manager import StorageManager

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
    # Always empty: a folder holds only files, which the user already may read to see this bin.
    hidden_contents: list[HiddenContents] = field(default_factory=list)
    contents_total: int = 0


class StorageRecycleBinService:
    def __init__(self, manager: "StorageManager"):
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
            "created_by_id",
        )

    @classmethod
    def to_entries(cls, org_id: int, rows, *, request=None) -> list[StorageRecycleBinEntry]:
        """Entries for a page of entry_rows; a folder lists what its restore brings back.

        `request` makes the avatar URLs of the "Created by" and "Deleted by" lines absolute.
        """
        rows = list(rows)
        parent_paths = {row[6] for row in rows if row[6]}
        live_folders = set(
            StorageFile.objects.filter(org_id=org_id, path__in=parent_paths).values_list(
                "path", flat=True
            )
        )
        authorship = authorship_details(
            StorageFile, {row[0]: BinEntryAuthorship(row[9], row[3]) for row in rows}, request
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
            _created_by_id,
        ) in rows:
            contents, total = (
                cls._folder_contents(org_id, path, batch) if item_type == "folder" else ([], 0)
            )
            entries.append(
                StorageRecycleBinEntry(
                    id=pk,
                    name=path,
                    item_type=item_type,
                    deleted_at=deleted_at,
                    days_left=RecycleBinService.days_left(deleted_at),
                    details=[
                        *authorship[pk],
                        *cls._details(
                            path,
                            item_type,
                            size,
                            parent_path,
                            created_at,
                            updated_at,
                            folder_is_live=not parent_path or parent_path in live_folders,
                        ),
                    ],
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
        return cls._folder_contents(org_id, row.path, row.soft_delete_batch, limit=SHOW_ALL_LIMIT)

    @staticmethod
    def _folder_contents(
        org_id: int, folder_path: str, batch: uuid.UUID, limit: int | None = CONTENTS_LIMIT
    ) -> tuple[list[BinContent], int]:
        """The rows deleted with the folder, under its path (at most `limit`, None for all).

        Two queries per folder on the page. Scoped to the org as well as the batch: a batch
        id never crosses orgs, but nothing here should rest on that.
        """
        rows = StorageFile.deleted_objects.filter(
            org_id=org_id, soft_delete_batch=batch, path__startswith=folder_path
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

    def purge_many(
        self,
        org_id: int,
        row_ids: list[int] | None,
        *,
        actor: str,
        until: float | None = None,
    ) -> BulkPurgeResult:
        """Purge each id, or every binned row of the org when `row_ids` is None.

        An id an earlier folder purge already removed is skipped. `until` is a
        `time.monotonic()` deadline, checked after each row: past it, the rest is left
        for a later call.

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
            if until is not None and time.monotonic() >= until:
                break
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
            CrossOrgCascadeError: the delete would reach another organization's row
                (a flow or surface of another org linked to the file); nothing is purged.
        """
        with transaction.atomic():
            batch_rows, root = self._lock_batch_of(org_id, row_id)
            batch = root.soft_delete_batch
            doomed = (
                [row.pk for row in batch_rows if row.path.startswith(root.path)]
                if root.item_type == "folder"
                else [root.pk]
            )
            self._checked_collector(org_id, doomed, f"storage entry {row_id}").delete()
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
        """Purge a whole batch binned before `cutoff`. Returns the rows purged, 0 if any row is locked.

        Raises:
            CrossOrgCascadeError: the delete would reach another organization's row;
                the batch stays in the bin.
        """
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
            self._checked_collector(org_id, locked, f"storage batch {batch}").delete()
            self._manager.delete_trash_batch(org_id, batch)

        logger.info(
            "Purged storage batch {batch} of org {org_id} ({count} rows) by {actor}",
            batch=batch,
            org_id=org_id,
            count=len(locked),
            actor=actor,
        )
        return len(locked)

    @classmethod
    def binned_bytes(cls, org_id: int) -> int:
        """Bytes the org's storage bin holds: what purging all of it would free."""
        return cls.binned(org_id).aggregate(total=Sum("size"))["total"] or 0

    def make_room(self, org_id: int, needed_bytes: int, *, actor: str) -> list[PurgedBinEntry]:
        """Purge the org's oldest storage bin entries, just enough of them to free `needed_bytes`.

        Entries go oldest deletion first, a folder whole with what was deleted with it;
        an entry that frees no bytes is kept. Only the org's bin rows are touched, never a
        live file. The caller holds the org row lock in its transaction (see
        record_files_within_quota), so writers of one org pick and use freed bytes one
        at a time; the rows picked are locked too, against a user or retention purge.

        An entry whose delete would reach another organization's row (see
        CascadeOrgGuard) is logged and kept, and the next oldest entries are picked in
        its place.

        Rows are deleted now, their trash objects only once the transaction commits. A
        rollback then leaves every binned row with its objects, and an object delete that
        fails after the commit leaves only trash nothing points at, which is logged.
        Each purged entry is logged once the transaction commits, with `actor` (who caused
        the write) as the manual purge logs it.

        Raises:
            StorageQuotaExceeded: the whole bin, minus the entries kept, frees less than
                `needed_bytes`; nothing is purged.
        """
        refused: set[int] = set()
        while True:
            entries, rows_by_batch = self._lock_entries_freeing(org_id, needed_bytes, refused)
            doomed_ids = [row.pk for _, entry_rows in entries for row in entry_rows]
            try:
                # Quiet: on a refusal each entry is checked on its own, which logs it.
                collector = self._checked_collector(
                    org_id,
                    doomed_ids,
                    f"{len(entries)} storage bin entries",
                    log_refusal=False,
                )
                break
            except CrossOrgCascadeError:
                newly_refused = self._refused_entries(org_id, entries)
                if not newly_refused:
                    # Refused together, though no entry is on its own: the quiet check
                    # logged nothing, so this is the only trace of the 409.
                    logger.error(
                        "Refused to delete {model} {ids} of org {org_id} to make room: "
                        "the entries together reach another organization's row, "
                        "though none does on its own",
                        model=StorageFile.__name__,
                        ids=sorted(doomed_ids),
                        org_id=org_id,
                    )
                    raise
                refused |= newly_refused

        purged = [
            PurgedBinEntry(name=root.path, size=sum(row.size or 0 for row in entry_rows))
            for root, entry_rows in entries
        ]
        doomed_in_batch: dict[uuid.UUID, int] = defaultdict(int)
        for root, entry_rows in entries:
            doomed_in_batch[root.soft_delete_batch] += len(entry_rows)
        # A batch left with no rows goes with its whole trash prefix, as in purge().
        emptied = {
            batch for batch, count in doomed_in_batch.items() if count == len(rows_by_batch[batch])
        }
        trash: list[tuple[uuid.UUID, str | None]] = [
            (root.soft_delete_batch, root.path)
            for root, _ in entries
            if root.soft_delete_batch not in emptied
        ]
        trash += [(batch, None) for batch in emptied]

        collector.delete()
        transaction.on_commit(lambda: self._finish_quota_purge(org_id, purged, trash, actor))
        return purged

    def _lock_entries_freeing(
        self, org_id: int, needed_bytes: int, skipped: set[int]
    ) -> tuple[list[tuple[StorageFile, list[StorageFile]]], dict[uuid.UUID, list[StorageFile]]]:
        """Pick and lock the oldest entries freeing `needed_bytes`, leaving out the `skipped` ones.

        Returns each entry's top-level row with the rows its purge deletes, and every
        locked row of the batches picked, by batch.

        Raises:
            StorageQuotaExceeded: the bin, minus `skipped`, frees less.
        """
        chosen = self._oldest_entries_freeing(org_id, needed_bytes, skipped)
        rows_by_batch: dict[uuid.UUID, list[StorageFile]] = defaultdict(list)
        # One ordered statement, as _lock_batch_of locks a batch: no lock-order deadlock.
        for row in (
            StorageFile.deleted_objects.select_for_update()
            .filter(org_id=org_id, soft_delete_batch__in={batch for _, batch in chosen})
            .order_by("path", "pk")
        ):
            rows_by_batch[row.soft_delete_batch].append(row)

        entries: list[tuple[StorageFile, list[StorageFile]]] = []
        for entry_id, batch in chosen:
            batch_rows = rows_by_batch[batch]
            root = next((row for row in batch_rows if row.pk == entry_id), None)
            if root is None:
                continue  # purged by someone else since it was picked
            entry_rows = (
                [row for row in batch_rows if row.path.startswith(root.path)]
                if root.item_type == "folder"
                else [root]
            )
            entries.append((root, entry_rows))
        return entries, rows_by_batch

    def _refused_entries(
        self, org_id: int, entries: list[tuple[StorageFile, list[StorageFile]]]
    ) -> set[int]:
        """Ids of the entries whose delete the guard refuses, each refusal logged once."""
        refused: set[int] = set()
        for root, entry_rows in entries:
            try:
                self._checked_collector(
                    org_id, [row.pk for row in entry_rows], f"storage entry {root.pk}"
                )
            except CrossOrgCascadeError:
                refused.add(root.pk)
        return refused

    @staticmethod
    def _checked_collector(
        org_id: int, pks: list[int], description: str, *, log_refusal: bool = True
    ) -> Collector:
        """Collect what deleting the storage rows `pks` of `org_id` changes, checked by the guard.

        What QuerySet.delete() does, with the collected rows checked before anything
        is deleted: a file linked to another organization's flow or surface would take
        that link row with it (GraphStorageFile and SurfaceStorageItem cascade from
        StorageFile). Call delete() on the result to delete.

        Raises:
            CrossOrgCascadeError: the delete would change another organization's row.
        """
        using = router.db_for_write(StorageFile)
        rows = StorageFile.all_objects.using(using).filter(pk__in=pks)
        collector = Collector(using=using, origin=rows)
        collector.collect(rows)
        CascadeOrgGuard(org_id, description, using, log_refusal=log_refusal).check_collected(
            collector
        )
        return collector

    @classmethod
    def _oldest_entries_freeing(
        cls, org_id: int, needed_bytes: int, skipped: set[int]
    ) -> list[tuple[int, uuid.UUID]]:
        """(pk, batch) of the fewest oldest top-level entries freeing `needed_bytes`, read unlocked.

        Raises:
            StorageQuotaExceeded: the whole bin, minus the `skipped` entries, frees less.
        """
        deleted_with_folder = (
            StorageFile.deleted_objects.filter(
                org_id=OuterRef("org_id"),
                soft_delete_batch=OuterRef("soft_delete_batch"),
                path__startswith=OuterRef("path"),
            )
            .order_by()
            .values("soft_delete_batch")
            .annotate(total=Sum("size"))
            .values("total")
        )
        entries = (
            cls.top_level(org_id)
            .exclude(pk__in=skipped)
            .annotate(
                freed=Case(
                    When(item_type="folder", then=Coalesce(Subquery(deleted_with_folder), 0)),
                    default=Coalesce("size", 0),
                    output_field=BigIntegerField(),
                )
            )
            .filter(freed__gt=0)
            .order_by("soft_deleted_at", "path", "pk")
            .values_list("pk", "soft_delete_batch", "freed")
        )
        chosen: list[tuple[int, uuid.UUID]] = []
        freed = 0
        for pk, batch, size in entries.iterator(chunk_size=200):
            chosen.append((pk, batch))
            freed += size
            if freed >= needed_bytes:
                return chosen
        raise StorageQuotaExceeded()

    def _finish_quota_purge(
        self,
        org_id: int,
        purged: list[PurgedBinEntry],
        trash: list[tuple[uuid.UUID, str | None]],
        actor: str,
    ) -> None:
        """Log the committed quota purge and delete its trash objects: a whole batch for None."""
        for entry in purged:
            logger.info(
                "Purged storage bin entry {path} ({size} bytes) of org {org_id} by {actor}, "
                "reason: storage quota",
                path=entry.name,
                size=entry.size,
                org_id=org_id,
                actor=actor,
            )
        for batch, path in trash:
            try:
                if path is None:
                    self._manager.delete_trash_batch(org_id, batch)
                else:
                    self._manager.delete_trash_path(org_id, batch, path)
            except Exception:
                # The rows are gone and committed: what is left is trash nothing points
                # at. Another write must not fail over it.
                logger.exception(
                    "Trash objects of {path} in batch {batch} of org {org_id} were left behind "
                    "after a storage quota purge",
                    path=path or "(whole batch)",
                    batch=batch,
                    org_id=org_id,
                )

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
