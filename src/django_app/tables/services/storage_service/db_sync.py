from collections.abc import Mapping

from django.db import transaction
from django.db.models import Value
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


_BULK_BATCH = 1000


class StorageFileSync:
    """
    Keeps the StorageFile DB table in sync with storage mutations.
    All path arguments are org-relative (no org_X/ prefix).

    `user` is the acting user (system callers pass none): rows a call creates are authored
    and last edited by it, and an existing row the call edits is only last edited by it;
    its author, or the lack of one, is kept.
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

        created_folders = _create_missing_folders(org, _ancestor_paths(path), author)
        record_last_edits([file_row, *created_folders], user)

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
    def on_bulk_upload(
        org_id: int,
        files: list[tuple[str, int]],
        folders=(),
        *,
        user: object | None = None,
        authors_by_path: Mapping[str, int | None] | None = None,
    ) -> None:
        """on_upload for many files [(path, size)] and empty folders at once, in two INSERTs.

        Args:
            authors_by_path: Author id of each inserted row whose path it names, overriding
                `user`; a cross-org move uses it so moved rows keep their own authors. It
                only applies to rows this call inserts: an existing file or folder keeps
                its author. Paths it does not name (e.g. new ancestor folders) are
                authored by `user`.
        """
        folder_paths = {folder.rstrip("/") + "/" for folder in folders}
        for path in [*(path for path, _ in files), *folder_paths]:
            folder_paths.update(_ancestor_paths(path))

        # `user` authors the rows created here, unless `authors_by_path` names them, and last
        # edits the files and the new folders; folders that already existed are left as they are.
        author = resolve_author(user)
        author_overrides = authors_by_path or {}

        def author_id_of(path: str) -> int | None:
            if path in author_overrides:
                return author_overrides[path]
            return author.pk if author is not None else None

        existing_folder_paths = (
            set(
                StorageFile.objects.filter(org_id=org_id, path__in=folder_paths).values_list(
                    "path", flat=True
                )
            )
            if user is not None
            else set()
        )

        StorageFile.objects.bulk_create(
            [
                StorageFile(
                    org_id=org_id,
                    path=path,
                    name=_name_of(path),
                    item_type="folder",
                    parent_path=_parent_of(path),
                    created_by_id=author_id_of(path),
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
                    created_by_id=author_id_of(path),
                )
                for path, size in files
            ],
            # NOTE: never add created_by to update_fields: an existing file keeps its author.
            update_conflicts=True,
            unique_fields=["org", "path"],
            update_fields=["name", "item_type", "parent_path", "size", "updated_at"],
            batch_size=_BULK_BATCH,
        )
        if user is not None:
            edited_paths = [*(path for path, _ in files), *(folder_paths - existing_folder_paths)]
            record_last_edits(
                StorageFile.objects.filter(org_id=org_id, path__in=edited_paths), user
            )

    @staticmethod
    def on_mkdir(org_id: int, path: str, *, user: object | None = None) -> None:
        org = Organization.objects.get(id=org_id)
        author = resolve_author(user)
        folder_path = path.rstrip("/") + "/"

        created_folders = _create_missing_folders(
            org, [folder_path, *_ancestor_paths(folder_path)], author
        )
        record_last_edits(created_folders, user)

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
        parent_path. The moved entry's own row is last edited by `user` and keeps its
        author, or the lack of one; rows beneath a moved folder keep their authors and last
        edits.
        """
        with transaction.atomic():
            updated = 0

            if not dst.endswith("/"):
                updated = StorageFile.objects.filter(org_id=org_id, path=src).update(
                    path=dst,
                    name=_name_of(dst),
                    parent_path=_parent_of(dst),
                )
                if updated:
                    record_last_edits(StorageFile.objects.filter(org_id=org_id, path=dst), user)

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
                record_last_edits([row for row in moved_rows if row.path == dst_prefix], user)
