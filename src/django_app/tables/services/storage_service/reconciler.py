from django.utils.dateparse import parse_datetime

from tables.models import Organization, StorageFile
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.db_sync import (
    _name_of,
    _parent_of,
    _ancestor_paths,
)


class StorageReconciler:
    """
    Reconciles StorageFile DB rows against the storage backend for a given org.

    Designed for one-time backfill at deploy and periodic drift recovery.
    Not used in the per-request read path — listing reads from DB directly.
    """

    def __init__(self, backend: AbstractStorageBackend):
        self._backend = backend

    def reconcile_tree(self, org_id: int, prefix: str = "") -> None:
        org = Organization.objects.get(id=org_id)
        org_prefix = f"org_{org_id}/"
        full_prefix = org_prefix + prefix

        raw_objects = self._backend.list_all_objects(full_prefix)

        rows_to_upsert: list[StorageFile] = []
        desired_paths: set[str] = set()
        ancestor_paths: set[str] = set()

        for key, size, modified_iso in raw_objects:
            if not key.startswith(org_prefix):
                continue
            rel_path = key[len(org_prefix) :]

            desired_paths.add(rel_path)

            s3_modified = parse_datetime(modified_iso)
            rows_to_upsert.append(
                StorageFile(
                    org=org,
                    path=rel_path,
                    name=_name_of(rel_path),
                    item_type="file",
                    size=size,
                    s3_modified=s3_modified,
                    parent_path=_parent_of(rel_path),
                )
            )

            for anc in _ancestor_paths(rel_path):
                ancestor_paths.add(anc)

        for folder_path in ancestor_paths:
            if folder_path not in desired_paths:
                desired_paths.add(folder_path)
                rows_to_upsert.append(
                    StorageFile(
                        org=org,
                        path=folder_path,
                        name=_name_of(folder_path),
                        item_type="folder",
                        size=None,
                        s3_modified=None,
                        parent_path=_parent_of(folder_path),
                    )
                )

        batch_size = 1000
        for i in range(0, len(rows_to_upsert), batch_size):
            batch = rows_to_upsert[i : i + batch_size]
            StorageFile.objects.bulk_create(
                batch,
                update_conflicts=True,
                unique_fields=["org", "path"],
                update_fields=[
                    "name",
                    "item_type",
                    "size",
                    "s3_modified",
                    "parent_path",
                ],
                batch_size=batch_size,
            )

        stale_ids: list[int] = []
        db_prefix = prefix if prefix else ""
        qs = StorageFile.objects.filter(org_id=org_id)
        if db_prefix:
            qs = qs.filter(path__startswith=db_prefix)

        for file_id, path in qs.values_list("id", "path").iterator(chunk_size=2000):
            if path not in desired_paths:
                stale_ids.append(file_id)

        for i in range(0, len(stale_ids), batch_size):
            StorageFile.objects.filter(id__in=stale_ids[i : i + batch_size]).delete()
