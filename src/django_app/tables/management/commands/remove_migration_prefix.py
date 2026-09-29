from django.core.management.base import BaseCommand
from loguru import logger
from tables.models.knowledge_models import SourceCollection

MIGRATE_PREFIX = "COLLECTION_MIGRATE_"


class Command(BaseCommand):
    help = "Remove COLLECTION_MIGRATE_ prefix from collection names after migration is complete."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be renamed, don't actually update",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        migrated_collections = SourceCollection.objects.filter(
            collection_name__startswith=MIGRATE_PREFIX
        )

        if not migrated_collections.exists():
            logger.info(f"No collections found with prefix '{MIGRATE_PREFIX}'")
            self.stdout.write(
                self.style.WARNING(f"No collections found with prefix '{MIGRATE_PREFIX}'")
            )
            return

        count = migrated_collections.count()
        logger.info(f"Found {count} collections with migration prefix")
        self.stdout.write(self.style.SUCCESS(f"Found {count} collections with migration prefix"))

        success_count = 0
        error_count = 0

        for collection in migrated_collections:
            old_name = collection.collection_name
            new_name = old_name[len(MIGRATE_PREFIX) :]

            if dry_run:
                logger.info(f"[DRY-RUN] Would rename: '{old_name}' -> '{new_name}'")
                self.stdout.write(f"  [DRY-RUN] '{old_name}' -> '{new_name}'")
                continue

            try:
                collection.collection_name = new_name
                collection.save(update_fields=["collection_name", "updated_at"])

                logger.success(f"Renamed: '{old_name}' -> '{new_name}'")
                self.stdout.write(self.style.SUCCESS(f"  OK: '{old_name}' -> '{new_name}'"))
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to rename '{old_name}': {e}")
                self.stdout.write(self.style.ERROR(f"  FAIL: '{old_name}' - {e}"))
                error_count += 1

        # Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run completed - no changes made"))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Renaming completed: {success_count} successful, {error_count} failed"
                )
            )
        logger.info(f"Renaming completed: {success_count} successful, {error_count} failed")
