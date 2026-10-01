from collections.abc import Iterable

from django.db import transaction
from django.db.models import QuerySet, Value
from django.db.models.functions import Concat, Substr
from rbac.authorship import record_last_edits, resolve_author
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


def _record_edited(rows: Iterable[StorageFile], user: object | None) -> None:
    """Record `user` as the last editor of `rows`; without an acting user nothing is recorded."""
    if user is not None:
        record_last_edits(rows, user)


def _claim_unauthored(rows: QuerySet[StorageFile], author: User | None) -> None:
    """Make `author` the author of the rows in `rows` that have none.

    The NULL check runs in the UPDATE itself, so a concurrent claim is never overwritten.
    """
    if author is not None:
        rows.filter(created_by__isnull=True).update(created_by=author)


def _create_missing_rows(org: Organization, rows: list[StorageFile], user: object | None) -> None:
    """Insert `rows`, leaving paths already tracked untouched; `user` last edits the inserted ones."""
    # NOTE: the already-tracked paths are read before the insert, so a row that a
    # concurrent writer inserts between the read and the insert is taken for one inserted
    # here and recorded as last edited by `user`. Accepted: only the last edit is wrong.
    tracked_paths = set(
        StorageFile.objects.filter(org=org, path__in=[row.path for row in rows]).values_list(
            "path", flat=True
        )
    )
    StorageFile.objects.bulk_create(rows, ignore_conflicts=True)
    new_paths = [row.path for row in rows if row.path not in tracked_paths]
    if new_paths:
        _record_edited(StorageFile.objects.filter(org=org, path__in=new_paths), user)


def _create_missing_folders(
    org: Organization, folder_paths: list[str], author: User | None
) -> list[StorageFile]:
    """Create the folder rows of `folder_paths` that do not exist yet and return them."""
    created_rows = []
    for folder_path in folder_paths:
        folder_row, created = StorageFile.objects.get_or_create(
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
        if created:
            created_rows.append(folder_row)
    return created_rows


class StorageFileSync:
    """
    Keeps the StorageFile DB table in sync with storage mutations.
    All path arguments are org-relative (no org_X/ prefix).

    `user` is the acting user (system callers pass none): rows a call creates are authored
    and last edited by it, and an existing row the call edits is last edited by it and
    claimed by it when unauthored.
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

        created_folders = _create_missing_folders(org, _ancestor_paths(path), author)
        _record_edited([file_row, *created_folders], user)

    @staticmethod
    def on_mkdir(org_id: int, path: str, *, user: object | None = None) -> None:
        org = Organization.objects.get(id=org_id)
        author = resolve_author(user)
        folder_path = path.rstrip("/") + "/"

        created_folders = _create_missing_folders(
            org, [folder_path, *_ancestor_paths(folder_path)], author
        )
        _record_edited(created_folders, user)

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
        Sync a move/rename to `dst`, the ACTUAL backend destination: a file path, or a
        folder base path ending in "/".

        A `dst` without "/" first tries a single-row file update; otherwise (src was a
        folder) every row under `src` gets the `dst` prefix and a recomputed name and
        parent_path. The moved entry's own row is last edited by `user` and claimed by it
        when unauthored; rows beneath a moved folder keep their authors and last edits.
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
                    moved_file = StorageFile.objects.filter(org_id=org_id, path=dst)
                    _claim_unauthored(moved_file, author)
                    _record_edited(moved_file, user)

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
                _record_edited([row for row in moved_rows if row.path == dst_prefix], user)

    @staticmethod
    def on_copy(org_id: int, actual_dst_paths: list[str], *, user: object | None = None) -> None:
        """
        Sync a copy from the backend's actual destination paths ("/"-suffixed = folders).

        Every path's ancestor folders are created too, so intermediate directories exist
        even if the copy created no direct child of them. Rows that already exist are left
        untouched; the created rows are last edited by `user`.
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

        _create_missing_rows(org, rows, user)

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
        Destination rows are new rows authored and last edited by `user`; an
        existing destination file is last edited by it and claimed by it when
        unauthored.
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

                created_folders = _create_missing_folders(
                    dst_org, _ancestor_paths(actual_dst_path), author
                )
                _record_edited([dest_row, *created_folders], user)

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

            _create_missing_rows(dst_org, translated_rows, user)
            created_folders = _create_missing_folders(
                dst_org, _ancestor_paths(actual_dst_path), author
            )
            _record_edited(created_folders, user)

            StorageFile.objects.filter(org_id=src_org_id, path__startswith=src_prefix).delete()
