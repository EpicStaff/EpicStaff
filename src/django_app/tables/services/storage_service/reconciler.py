from django.utils.dateparse import parse_datetime
from rbac.models import Organization
from tables.models import StorageFile
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.db_sync import (
    _ancestor_paths,
    _name_of,
    _parent_of,
)
from tables.services.storage_service.path_utils import TRASH_DIRECTORY, is_trash_path

_SYNCED_FIELDS = ["name", "item_type", "size", "s3_modified", "parent_path"]
_BATCH_SIZE = 1000


class StorageReconciler:
    """
    Reconciles StorageFile DB rows against the storage backend for a given org.

    Designed for one-time backfill at deploy and periodic drift recovery.
    Not used in the per-request read path — listing reads from DB directly.
    """

    def __init__(self, backend: AbstractStorageBackend):
        self._backend = backend

    def reconcile_tree(self, org_id: int, prefix: str = "") -> None:
        """Make the org's live StorageFile rows match the backend's objects under `prefix`.

        Recycle-bin rows are left alone: their objects live under the reserved
        trash folder, which is skipped here, so they are neither re-created as
        live files nor swept as stale.

        Raises:
            ValueError: `prefix` is inside the reserved recycle-bin folder.
        """
        if is_trash_path(prefix):
            raise ValueError(f"'{TRASH_DIRECTORY}' is not reconciled.")
        org = Organization.objects.get(id=org_id)
        org_prefix = f"org_{org_id}/"
        full_prefix = org_prefix + prefix

        raw_objects = self._backend.list_all_objects(full_prefix)

        desired: dict[str, StorageFile] = {}
        ancestor_paths: set[str] = set()

        for key, size, modified_iso in raw_objects:
            if not key.startswith(org_prefix):
                continue
            rel_path = key[len(org_prefix) :]
            if is_trash_path(rel_path):
                continue

            desired[rel_path] = StorageFile(
                org=org,
                path=rel_path,
                name=_name_of(rel_path),
                item_type="file",
                size=size,
                s3_modified=parse_datetime(modified_iso),
                parent_path=_parent_of(rel_path),
            )
            ancestor_paths.update(_ancestor_paths(rel_path))

        for folder_path in ancestor_paths:
            if folder_path not in desired:
                desired[folder_path] = StorageFile(
                    org=org,
                    path=folder_path,
                    name=_name_of(folder_path),
                    item_type="folder",
                    size=None,
                    s3_modified=None,
                    parent_path=_parent_of(folder_path),
                )

        # The unique (org, path) index only covers live rows, and an upsert
        # can't name a partial index as its conflict target, so this diffs
        # against the live rows instead.
        live_rows = StorageFile.objects.filter(org_id=org_id)
        if prefix:
            live_rows = live_rows.filter(path__startswith=prefix)
        existing = {row.path: row for row in live_rows.only("id", "path", *_SYNCED_FIELDS)}

        to_create = [row for path, row in desired.items() if path not in existing]
        to_update = []
        for path, wanted in desired.items():
            row = existing.get(path)
            if row is not None and any(
                getattr(row, field) != getattr(wanted, field) for field in _SYNCED_FIELDS
            ):
                for field in _SYNCED_FIELDS:
                    setattr(row, field, getattr(wanted, field))
                to_update.append(row)
        stale_ids = [row.id for path, row in existing.items() if path not in desired]

        # ignore_conflicts: an upload landing between the read above and this
        # insert already made the live row. ON CONFLICT DO NOTHING (no target)
        # honors the partial unique index.
        StorageFile.objects.bulk_create(to_create, batch_size=_BATCH_SIZE, ignore_conflicts=True)
        StorageFile.objects.bulk_update(to_update, _SYNCED_FIELDS, batch_size=_BATCH_SIZE)
        for start in range(0, len(stale_ids), _BATCH_SIZE):
            StorageFile.objects.filter(id__in=stale_ids[start : start + _BATCH_SIZE]).delete()
