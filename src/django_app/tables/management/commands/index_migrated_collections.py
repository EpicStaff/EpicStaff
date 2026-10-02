import time

import requests
from django.core.management.base import BaseCommand
from loguru import logger
from tables.models.knowledge_models import NaiveRag, SourceCollection

MIGRATE_PREFIX = "COLLECTION_MIGRATE_"


class Command(BaseCommand):
    help = "Index all migrated collections (with COLLECTION_MIGRATE_ prefix) by sending HTTP requests to the indexing endpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            type=str,
            default="http://localhost:8000",
            help="Base URL of the Django server (default: http://localhost:8000)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=10.0,
            help="Delay between requests in seconds (default: 1.0)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be indexed, don't actually send requests",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")
        delay = options["delay"]
        dry_run = options["dry_run"]

        endpoint_url = f"{base_url}/api/process-rag-indexing/"

        # Find all collections with migrate prefix
        migrated_collections = SourceCollection.objects.filter(
            collection_name__startswith=MIGRATE_PREFIX
        )

        if not migrated_collections.exists():
            logger.info(f"No collections found with prefix '{MIGRATE_PREFIX}'")
            self.stdout.write(
                self.style.WARNING(f"No collections found with prefix '{MIGRATE_PREFIX}'")
            )
            return

        logger.info(f"Found {migrated_collections.count()} migrated collections to index")
        self.stdout.write(
            self.style.SUCCESS(f"Found {migrated_collections.count()} migrated collections")
        )

        success_count = 0
        error_count = 0

        for collection in migrated_collections:
            # Find NaiveRag for this collection via BaseRagType
            # BaseRagType.source_collection -> SourceCollection (FK)
            # NaiveRag.base_rag_type -> BaseRagType (FK)
            naive_rag = NaiveRag.objects.filter(base_rag_type__source_collection=collection).first()

            if not naive_rag:
                logger.warning(
                    f"No NaiveRag found for collection '{collection.collection_name}' "
                    f"(collection_id={collection.collection_id})"
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP: No NaiveRag for collection '{collection.collection_name}'"
                    )
                )
                continue

            rag_id = naive_rag.naive_rag_id

            if dry_run:
                logger.info(
                    f"[DRY-RUN] Would index NaiveRag id={rag_id} "
                    f"for collection '{collection.collection_name}'"
                )
                self.stdout.write(
                    f"  [DRY-RUN] Would index NaiveRag id={rag_id} "
                    f"for '{collection.collection_name}'"
                )
                continue

            # Send HTTP POST request to indexing endpoint
            payload = {
                "rag_id": rag_id,
                "rag_type": "naive",
            }

            try:
                logger.info(
                    f"Sending indexing request for NaiveRag id={rag_id} "
                    f"(collection: {collection.collection_name})"
                )
                response = requests.post(
                    endpoint_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 202:
                    logger.success(f"Successfully queued indexing for NaiveRag id={rag_id}")
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  OK: Indexed NaiveRag id={rag_id} for '{collection.collection_name}'"
                        )
                    )
                    success_count += 1
                else:
                    logger.error(
                        f"Failed to index NaiveRag id={rag_id}: "
                        f"{response.status_code} - {response.text}"
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"  FAIL: NaiveRag id={rag_id} - "
                            f"{response.status_code}: {response.text}"
                        )
                    )
                    error_count += 1

            except requests.RequestException as e:
                logger.error(f"Request failed for NaiveRag id={rag_id}: {e}")
                self.stdout.write(self.style.ERROR(f"  ERROR: NaiveRag id={rag_id} - {e}"))
                error_count += 1

            # Wait before next request
            if delay > 0:
                time.sleep(delay)

        # Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run completed - no requests sent"))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Indexing completed: {success_count} successful, {error_count} failed"
                )
            )
            logger.success("Run command for remove prefix from collection names")
            logger.success(
                "Command: [docker exec -it django_app python manage.py remove_migration_prefix --dry-run] - for preview."
                "[docker exec -it django_app python manage.py remove_migration_prefix] - execute"
            )
        logger.info(f"Indexing completed: {success_count} successful, {error_count} failed")
