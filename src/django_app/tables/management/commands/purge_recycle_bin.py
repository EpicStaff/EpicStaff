from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Permanently delete recycle-bin items older than DJANGO_RECYCLE_BIN_RETENTION_DAYS. "
        "Safe to run while the web server's daily job runs."
    )

    def handle(self, *args, **options):
        from tables.services.recycle_bin.purge_service import PurgeService

        counts = PurgeService.purge_expired(actor="purge_recycle_bin command")
        if not counts:
            self.stdout.write("Nothing to purge.")
            return
        for label, count in sorted(counts.items()):
            self.stdout.write(f"Purged {count} {label}")
