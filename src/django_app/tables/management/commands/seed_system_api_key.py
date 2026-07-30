import os

from django.core.management.base import BaseCommand

from tables.services.rbac.api_key.system_key_service import SystemKeyService


class Command(BaseCommand):
    help = (
        "Seed or rotate the singleton system API key from the DJANGO_API_KEY env var."
    )

    def handle(self, *args, **options):
        raw_key = os.environ.get("DJANGO_API_KEY", "")
        key = SystemKeyService().seed_from_env(raw_key)
        if key is None:
            self.stderr.write(
                self.style.WARNING(
                    "DJANGO_API_KEY is not set — no system key seeded; "
                    "internal services (realtime) cannot authenticate."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"System API key active (prefix={key.prefix}).")
        )
