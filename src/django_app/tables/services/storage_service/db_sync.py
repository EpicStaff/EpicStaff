from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Concat, Substr


def _name_of(path: str) -> str:
    """Return the last path segment (filename) from an org-relative path."""
    return path.rstrip("/").split("/")[-1]


class StorageFileSync:
    """
    Keeps the StorageFile DB table in sync with storage mutations.
    All path arguments are org-relative (no org_X/ prefix).
    """

    @staticmethod
    def on_upload(org_id: int, path: str) -> None:
        from tables.models import Organization, StorageFile

        org = Organization.objects.get(id=org_id)
        StorageFile.objects.get_or_create(
            org=org,
            path=path,
            defaults={"name": _name_of(path)},
        )

    @staticmethod
    def on_delete(org_id: int, path: str) -> None:
        from tables.models import StorageFile

        deleted, _ = StorageFile.objects.filter(org_id=org_id, path=path).delete()
        if deleted == 0:
            # It was a folder — delete all files under that prefix
            prefix = path.rstrip("/") + "/"
            StorageFile.objects.filter(org_id=org_id, path__startswith=prefix).delete()

    @staticmethod
    def on_move(org_id: int, src: str, dst: str) -> None:
        from tables.models import StorageFile

        with transaction.atomic():
            updated = StorageFile.objects.filter(org_id=org_id, path=src).update(
                path=dst,
                name=_name_of(dst),
            )
            if updated == 0:
                # Folder prefix move — recompute name per-row via ORM expression.
                # Using Concat/Substr keeps it a single UPDATE; name derives from
                # the new path suffix after the destination prefix.
                src_prefix = src.rstrip("/") + "/"
                dst_prefix = dst.rstrip("/") + "/"

                qs = StorageFile.objects.filter(
                    org_id=org_id, path__startswith=src_prefix
                )
                # Build new_path expression first, then derive name from the
                # suffix that follows the last "/" in the new path.  Because
                # folder moves don't change the filename segment, name stays
                # the same — so we only update path and leave name untouched.
                qs.update(
                    path=Concat(Value(dst_prefix), Substr("path", len(src_prefix) + 1))
                )

    @staticmethod
    def on_copy(org_id: int, actual_dst_paths: list[str]) -> None:
        from tables.models import Organization, StorageFile

        org = Organization.objects.get(id=org_id)
        StorageFile.objects.bulk_create(
            [StorageFile(org=org, path=p, name=_name_of(p)) for p in actual_dst_paths],
            ignore_conflicts=True,
        )

    @staticmethod
    def on_move_cross_org(
        src_org_id: int, src_path: str, dst_org_id: int, dst_path: str
    ) -> None:
        from tables.models import Organization, StorageFile

        StorageFile.objects.filter(org_id=src_org_id, path=src_path).delete()
        dst_org = Organization.objects.get(id=dst_org_id)
        StorageFile.objects.get_or_create(
            org=dst_org,
            path=dst_path,
            defaults={"name": _name_of(dst_path)},
        )

    @staticmethod
    def on_copy_cross_org(dst_org_id: int, dst_path: str) -> None:
        from tables.models import Organization, StorageFile

        dst_org = Organization.objects.get(id=dst_org_id)
        StorageFile.objects.get_or_create(
            org=dst_org,
            path=dst_path,
            defaults={"name": _name_of(dst_path)},
        )
