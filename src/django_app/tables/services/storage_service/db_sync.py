from django.db import transaction
from django.db.models import QuerySet, Value
from django.db.models.functions import Concat, Substr
from rbac.authorship import resolve_author
from rbac.models import Organization
from tables.models import StorageFile, User


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


def _claim_unauthored(rows: QuerySet[StorageFile], author: User | None) -> None:
    """Make `author` the author of the rows in `rows` that have none.

    The NULL check runs in the UPDATE itself, so a concurrent claim is never overwritten.
    """
    if author is not None:
        rows.filter(created_by__isnull=True).update(created_by=author)


class StorageFileSync:
    """
    Keeps the StorageFile DB table in sync with storage mutations.
    All path arguments are org-relative (no org_X/ prefix).

    `user` is the acting user: rows a call creates are authored by it, and an existing
    row the call edits is claimed by it when unauthored. System callers pass no user.
    """

    @staticmethod
    def on_upload(
        org_id: int,
        path: str,
        size: int | None = None,
        s3_modified=None,
        *,
        user: object | None = None,
    ) -> None:
        org = Organization.objects.get(id=org_id)
        author = resolve_author(user)
        file_row, created = StorageFile.objects.get_or_create(
            org=org,
            path=path,
            defaults={
                "name": _name_of(path),
                "item_type": "file",
                "parent_path": _parent_of(path),
                "size": size,
                "s3_modified": s3_modified,
                "created_by": author,
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
            if file_row.created_by_id is None:
                _claim_unauthored(StorageFile.objects.filter(pk=file_row.pk), author)

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
                    "created_by": author,
                },
            )

    @staticmethod
    def on_mkdir(org_id: int, path: str, *, user: object | None = None) -> None:
        org = Organization.objects.get(id=org_id)
        author = resolve_author(user)
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
                "created_by": author,
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
                    "created_by": author,
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
    def on_move(org_id: int, src: str, dst: str, *, user: object | None = None) -> None:
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

        The moved entry's own row is claimed by `user` when unauthored; rows
        beneath a moved folder keep their authors.
        """
        author = resolve_author(user)
        with transaction.atomic():
            updated = 0

            if not dst.endswith("/"):
                updated = StorageFile.objects.filter(org_id=org_id, path=src).update(
                    path=dst,
                    name=_name_of(dst),
                    parent_path=_parent_of(dst),
                )
                if updated:
                    _claim_unauthored(StorageFile.objects.filter(org_id=org_id, path=dst), author)

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
                _claim_unauthored(
                    StorageFile.objects.filter(org_id=org_id, path=dst_prefix), author
                )

    @staticmethod
    def on_copy(org_id: int, actual_dst_paths: list[str], *, user: object | None = None) -> None:
        """
        Sync a copy operation using the actual destination paths returned by
        the backend. Paths ending in "/" are folder rows, the rest are file
        rows. Ancestor folders for every path are created too, so
        intermediate directories exist in the DB even if the copy created no
        direct child of them. Rows that already exist are left untouched.
        """
        org = Organization.objects.get(id=org_id)
        author = resolve_author(user)
        folder_paths: set[str] = set()
        rows = []

        for path in actual_dst_paths:
            folder_paths.update(_ancestor_paths(path))

            if path.endswith("/"):
                folder_paths.add(path)
                continue

            rows.append(
                StorageFile(
                    org=org,
                    path=path,
                    name=_name_of(path),
                    item_type="file",
                    parent_path=_parent_of(path),
                    created_by=author,
                )
            )

        for folder_path in folder_paths:
            rows.append(
                StorageFile(
                    org=org,
                    path=folder_path,
                    name=_name_of(folder_path),
                    item_type="folder",
                    parent_path=_parent_of(folder_path),
                    created_by=author,
                )
            )

        StorageFile.objects.bulk_create(rows, ignore_conflicts=True)

    @staticmethod
    def on_move_cross_org(
        src_org_id: int,
        src_path: str,
        dst_org_id: int,
        actual_dst_path: str,
        *,
        user: object | None = None,
    ) -> None:
        """
        Sync a cross-org move using the actual destination path returned by
        the backend: an exact file path, or a folder base path ending in "/".
        Destination rows are new rows authored by `user`; an existing
        destination file is claimed by it when unauthored.
        """
        dst_org = Organization.objects.get(id=dst_org_id)
        author = resolve_author(user)

        with transaction.atomic():
            if not actual_dst_path.endswith("/"):
                source_row = StorageFile.objects.filter(org_id=src_org_id, path=src_path).first()

                dest_row, created = StorageFile.objects.get_or_create(
                    org=dst_org,
                    path=actual_dst_path,
                    defaults={
                        "name": _name_of(actual_dst_path),
                        "item_type": "file",
                        "parent_path": _parent_of(actual_dst_path),
                        "size": source_row.size if source_row else None,
                        "s3_modified": source_row.s3_modified if source_row else None,
                        "created_by": author,
                    },
                )

                if not created:
                    if source_row is not None:
                        dest_row.size = source_row.size
                        dest_row.s3_modified = source_row.s3_modified
                        dest_row.save(update_fields=["size", "s3_modified"])
                    if dest_row.created_by_id is None:
                        _claim_unauthored(StorageFile.objects.filter(pk=dest_row.pk), author)

                for ancestor_path in _ancestor_paths(actual_dst_path):
                    StorageFile.objects.get_or_create(
                        org=dst_org,
                        path=ancestor_path,
                        defaults={
                            "name": _name_of(ancestor_path),
                            "item_type": "folder",
                            "parent_path": _parent_of(ancestor_path),
                            "created_by": author,
                        },
                    )

                StorageFile.objects.filter(org_id=src_org_id, path=src_path).delete()
                return

            src_prefix = src_path.rstrip("/") + "/"
            source_rows = list(
                StorageFile.objects.filter(org_id=src_org_id, path__startswith=src_prefix)
            )

            translated_rows = []
            for row in source_rows:
                if row.path == src_prefix:
                    new_path = actual_dst_path
                else:
                    new_path = actual_dst_path + row.path[len(src_prefix) :]

                translated_rows.append(
                    StorageFile(
                        org=dst_org,
                        path=new_path,
                        name=_name_of(new_path),
                        item_type=row.item_type,
                        parent_path=_parent_of(new_path),
                        size=row.size,
                        s3_modified=row.s3_modified,
                        created_by=author,
                    )
                )

            StorageFile.objects.bulk_create(translated_rows, ignore_conflicts=True)

            for ancestor_path in _ancestor_paths(actual_dst_path):
                StorageFile.objects.get_or_create(
                    org=dst_org,
                    path=ancestor_path,
                    defaults={
                        "name": _name_of(ancestor_path),
                        "item_type": "folder",
                        "parent_path": _parent_of(ancestor_path),
                        "created_by": author,
                    },
                )

            StorageFile.objects.filter(org_id=src_org_id, path__startswith=src_prefix).delete()
