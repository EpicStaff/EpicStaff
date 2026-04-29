from django.core.management.base import BaseCommand

from tables.services.storage_service.db_sync import _name_of


class Command(BaseCommand):
    help = "Upsert StorageFile rows from the storage backend for all orgs (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count keys without writing to the database.",
        )
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Restrict backfill to a single organization by ID.",
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
            # so we pass the full org prefix directly to list_all_keys.
            org_prefix = f"org_{org.id}/"
            keys: list[str] = backend.list_all_keys(org_prefix)

            total = len(keys)
            upserted = 0

            if dry_run:
                self.stdout.write(f"[org={org.id}] dry-run: {total} keys found")
                continue

            batch_size = 1000
            for i in range(0, total, batch_size):
                page = keys[i : i + batch_size]
                # Strip the org prefix — StorageFile.path is org-relative.
                objects = [
                    StorageFile(
                        org=org,
                        path=key[len(org_prefix) :],
                        name=_name_of(key),
                    )
                    for key in page
                ]
                StorageFile.objects.bulk_create(
                    objects,
                    update_conflicts=True,
                    unique_fields=["org", "path"],
                    update_fields=["name"],
                    batch_size=batch_size,
                )
                upserted += len(objects)
                self.stdout.write(f"[org={org.id}] upserted {upserted}/{total}")
