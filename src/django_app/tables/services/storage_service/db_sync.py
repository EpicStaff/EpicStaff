import uuid
from dataclasses import dataclass

from django.db import transaction
from django.db.models import QuerySet, Value
from django.db.models.functions import Concat, Substr
from django.utils import timezone
from rbac.models import Organization
from tables.models import StorageFile
from tables.services.storage_service.path_utils import is_trash_path


def _name_of(path: str) -> str:
    """Return the last path segment (filename) from an org-relative path."""
    return path.rstrip("/").split("/")[-1]


def _parent_of(path: str) -> str:
    """
    Return the immediate parent directory path, ending in '/', or '' at root.

    Examples:
        "a/b/c.txt" -> "a/b/"
        "c.txt"     -> ""
        "a/b/"      -> "a/"
        "a/"        -> ""
    """
    stripped = path.rstrip("/")
    if "/" not in stripped:
        return ""
    return stripped.rsplit("/", 1)[0] + "/"


def _ancestor_paths(path: str) -> list[str]:
    """
    Return all ancestor folder paths for a given path, ordered from root to parent.

    For "a/b/c.txt" returns ["a/", "a/b/"].
    For "a/b/" returns ["a/"].
    For "a/" or "root.txt" returns [].
    """
    parts = path.rstrip("/").split("/")
    ancestors = []
    for i in range(1, len(parts)):
        ancestors.append("/".join(parts[:i]) + "/")
    return ancestors


_BULK_BATCH = 1000


@dataclass(frozen=True)
class SoftDeletedSubtree:
    """What a soft delete binned: one batch, rooted at a file path or a folder path ending in "/"."""

    batch: uuid.UUID
    root_path: str


class StorageFileSync:
    """
    Keeps the StorageFile DB table in sync with storage mutations.
    All path arguments are org-relative (no org_X/ prefix).
    """

    @staticmethod
    def on_upload(
        org_id: int,
        path: str,
        size: int | None = None,
        s3_modified=None,
    ) -> None:
        if is_trash_path(path):
            return  # recycle-bin objects are never live files
        org = Organization.objects.get(id=org_id)
        file_row, created = StorageFile.objects.get_or_create(
            org=org,
            path=path,
            defaults={
                "name": _name_of(path),
                "item_type": "file",
                "parent_path": _parent_of(path),
                "size": size,
                "s3_modified": s3_modified,
            },
        )

        if not created:
            update_fields = ["name", "item_type", "parent_path"]
            file_row.name = _name_of(path)
            file_row.item_type = "file"
            file_row.parent_path = _parent_of(path)

            if size is not None:
                file_row.size = size
                update_fields.append("size")

            if s3_modified is not None:
                file_row.s3_modified = s3_modified
                update_fields.append("s3_modified")

            file_row.save(update_fields=update_fields)

        for ancestor_path in _ancestor_paths(path):
            StorageFile.objects.get_or_create(
                org=org,
                path=ancestor_path,
                defaults={
                    "name": _name_of(ancestor_path),
                    "item_type": "folder",
                    "parent_path": _parent_of(ancestor_path),
                    "size": None,
                    "s3_modified": None,
                },
            )

    @staticmethod
    def on_bulk_upload(org_id: int, files: list[tuple[str, int]], folders=()) -> None:
        """on_upload for many files [(path, size)] and empty folders at once, in two INSERTs."""
        folder_paths = {folder.rstrip("/") + "/" for folder in folders}
        for path in [*(path for path, _ in files), *folder_paths]:
            folder_paths.update(_ancestor_paths(path))

        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org_id=org_id,
                    path=path,
                    name=_name_of(path),
                    item_type="folder",
                    parent_path=_parent_of(path),
                )
                for path in sorted(folder_paths)
            ],
            ignore_conflicts=True,
            batch_size=_BULK_BATCH,
        )
        # Update the live rows that exist, insert the rest. An upsert can't do
        # it: the unique (org, path) index only covers live rows, and Django
        # can't name a partial index as the ON CONFLICT target.
        size_by_path = dict(files)
        now = timezone.now()
        existing = list(StorageFile.objects.filter(org_id=org_id, path__in=size_by_path))
        for row in existing:
            row.name = _name_of(row.path)
            row.item_type = "file"
            row.parent_path = _parent_of(row.path)
            row.size = size_by_path[row.path]
            row.updated_at = now
        StorageFile.objects.bulk_update(
            existing,
            ["name", "item_type", "parent_path", "size", "updated_at"],
            batch_size=_BULK_BATCH,
        )
        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org_id=org_id,
                    path=path,
                    name=_name_of(path),
                    item_type="file",
                    parent_path=_parent_of(path),
                    size=size,
                )
                for path, size in files
            ],
            # Every path, not only the new ones: a row binned since the read
            # above needs a new live row. Live rows conflict and are skipped.
            ignore_conflicts=True,
            batch_size=_BULK_BATCH,
        )

    @staticmethod
    def on_mkdir(org_id: int, path: str) -> None:
        org = Organization.objects.get(id=org_id)
        folder_path = path.rstrip("/") + "/"

        StorageFile.objects.get_or_create(
            org=org,
            path=folder_path,
            defaults={
                "name": _name_of(folder_path),
                "item_type": "folder",
                "parent_path": _parent_of(folder_path),
                "size": None,
                "s3_modified": None,
            },
        )

        for ancestor_path in _ancestor_paths(folder_path):
            StorageFile.objects.get_or_create(
                org=org,
                path=ancestor_path,
                defaults={
                    "name": _name_of(ancestor_path),
                    "item_type": "folder",
                    "parent_path": _parent_of(ancestor_path),
                    "size": None,
                    "s3_modified": None,
                },
            )

    @staticmethod
    def on_soft_delete(org_id: int, path: str) -> SoftDeletedSubtree | None:
        """Bin the live file at `path`, or the folder at `path` with everything under it, as one batch.

        Same lookup as on_delete: an exact live file path wins, otherwise `path`
        is a folder. Every row pointing at a binned row (flow attachments,
        session outputs, surface grants) is hard-deleted: a binned file is
        linked to nothing, and a restore brings it back without its links.
        Returns None when nothing live sits at `path`.
        """
        clean_path = path.rstrip("/")
        live_rows = StorageFile.objects.filter(org_id=org_id)
        if not path.endswith("/") and live_rows.filter(path=clean_path, item_type="file").exists():
            root_path = clean_path
            rows = live_rows.filter(path=clean_path)
        else:
            root_path = clean_path + "/"
            rows = live_rows.filter(path__startswith=root_path)
        if not rows.exists():
            return None

        batch = uuid.uuid4()
        binned = rows.update(active=False, soft_deleted_at=timezone.now(), soft_delete_batch=batch)
        if not binned:
            # A concurrent delete binned these rows first (the UPDATE waited for
            # its locks, then re-checked active=True). Its objects are its to move.
            return None
        _delete_links_to(StorageFile.all_objects.filter(soft_delete_batch=batch))
        return SoftDeletedSubtree(batch=batch, root_path=root_path)

    @staticmethod
    def on_delete(org_id: int, path: str) -> None:
        deleted, _ = StorageFile.objects.filter(org_id=org_id, path=path).delete()

        if deleted == 0:
            prefix = path.rstrip("/") + "/"
            StorageFile.objects.filter(org_id=org_id, path__startswith=prefix).delete()
            StorageFile.objects.filter(org_id=org_id, path=prefix).delete()

    @staticmethod
    def on_move(org_id: int, src: str, dst: str) -> None:
        """
        Sync a move/rename operation.

        dst is the ACTUAL destination path produced by the backend: an exact
        file path (no trailing "/") for a renamed/moved file, or a folder
        base path ending in "/" for a moved/renamed folder.

        When dst does not end in "/", first try an exact single-row update.
        If no row matches (src was a folder, not a file) or dst already ends
        in "/", fall back to the folder branch: rewrite the path prefix for
        every row under src, then recompute both parent_path and name for
        the rows that landed under dst.
        """
        with transaction.atomic():
            updated = 0

            if not dst.endswith("/"):
                updated = StorageFile.objects.filter(org_id=org_id, path=src).update(
                    path=dst,
                    name=_name_of(dst),
                    parent_path=_parent_of(dst),
                )

            if updated == 0:
                src_prefix = src.rstrip("/") + "/"
                dst_prefix = dst.rstrip("/") + "/"

                qs = StorageFile.objects.filter(org_id=org_id, path__startswith=src_prefix)
                qs.update(path=Concat(Value(dst_prefix), Substr("path", len(src_prefix) + 1)))

                moved_rows = list(
                    StorageFile.objects.filter(org_id=org_id, path__startswith=dst_prefix)
                )

                for row in moved_rows:
                    row.parent_path = _parent_of(row.path)
                    row.name = _name_of(row.path)

                StorageFile.objects.bulk_update(moved_rows, ["parent_path", "name"])


def _delete_links_to(rows: QuerySet) -> None:
    """Hard-delete every row that points at one of `rows`: a binned file is linked to nothing.

    The base manager reaches binned link rows too, such as a binned flow's
    attachment. Listed by hand rather than found by reflection, so a new link
    model is a deliberate choice (see test_every_storage_file_link_is_listed).
    """
    for model in storage_file_link_models():
        model._base_manager.filter(storage_file__in=rows).delete()


def storage_file_link_models() -> tuple[type, ...]:
    """Every model with a foreign key to StorageFile."""
    from agents.models import (
        AgentInlineSurfaceStorageItem,
        InlineSurfaceStorageItem,
        SurfaceStorageItem,
    )
    from tables.models import GraphStorageFile, SessionStorageFile

    return (
        GraphStorageFile,
        SessionStorageFile,
        SurfaceStorageItem,
        InlineSurfaceStorageItem,
        AgentInlineSurfaceStorageItem,
    )
