from django.core.management.base import BaseCommand

from tables.models import Organization
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.reconciler import StorageReconciler


class Command(BaseCommand):
    help = "Reconcile StorageFile rows against the storage backend for all orgs (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count objects without writing to the database.",
        )
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Restrict backfill to a single organization by ID.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        org_id_filter: int | None = options["org_id"]

        backend = get_storage_manager()._backend

        orgs = Organization.objects.all()
        if org_id_filter is not None:
            orgs = orgs.filter(id=org_id_filter)

        for org in orgs:
            if dry_run:
                org_prefix = f"org_{org.id}/"
                objects = backend.list_all_objects(org_prefix)
                self.stdout.write(
                    f"[org={org.id}] dry-run: {len(objects)} objects found"
                )
                continue

            StorageReconciler(backend).reconcile_tree(org.id, "")
            self.stdout.write(f"[org={org.id}] reconcile_tree complete")
