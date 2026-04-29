from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete StorageFile rows whose path no longer exists in the storage backend. "
        "Deleting a StorageFile also cascades to GraphStorageFile and SessionStorageFile rows "
        "that reference it, detaching it from any graphs or sessions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report orphan counts without deleting.",
        )
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Restrict pruning to a single organization by ID.",
        )

    def handle(self, *args, **options):
        from tables.models import Organization, StorageFile
        from tables.services.storage_service import get_storage_manager

        dry_run: bool = options["dry_run"]
        org_id_filter: int | None = options["org_id"]

        backend = get_storage_manager()._backend

        orgs = Organization.objects.all()
        if org_id_filter is not None:
            orgs = orgs.filter(id=org_id_filter)

        for org in orgs:
            # The manager's backend is initialized with organization_prefix="",
            # so pass the full org prefix directly to list_all_keys.
            org_prefix = f"org_{org.id}/"
            keys: list[str] = backend.list_all_keys(org_prefix)

            # Strip the org prefix — StorageFile.path is org-relative.
            s3_paths: set[str] = {key[len(org_prefix) :] for key in keys}
            s3_count = len(s3_paths)

            orphan_ids: list[int] = []
            db_count = 0
            for file_id, path in (
                StorageFile.objects.filter(org_id=org.id)
                .values_list("id", "path")
                .iterator(chunk_size=5000)
            ):
                db_count += 1
                if path not in s3_paths:
                    orphan_ids.append(file_id)

            orphan_count = len(orphan_ids)

            if dry_run:
                self.stdout.write(
                    f"[org={org.id}] {s3_count} keys in S3, {db_count} rows in DB, "
                    f"{orphan_count} orphans to prune"
                )
                continue

            if orphan_count == 0:
                self.stdout.write(f"[org={org.id}] no orphans found")
                continue

            batch_size = 1000
            pruned = 0
            for i in range(0, orphan_count, batch_size):
                batch = orphan_ids[i : i + batch_size]
                StorageFile.objects.filter(id__in=batch).delete()
                pruned += len(batch)
                self.stdout.write(f"[org={org.id}] pruned {pruned}/{orphan_count}")
