from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Concat, Substr
from rbac.models import Organization
from tables.models import StorageFile


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
        """on_upload for many files [(path, size)] and extra (empty) folders at once:
        two INSERTs instead of several queries per file, which matters while the
        caller holds the org lock over a whole unpacked archive."""
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
            update_conflicts=True,
            unique_fields=["org", "path"],
            update_fields=["name", "item_type", "parent_path", "size", "updated_at"],
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
