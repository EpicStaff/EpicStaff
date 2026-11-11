from django.conf import settings
from django.core.management.base import BaseCommand

from rbac.identity.api_keys.system_key import SystemKeyService


class Command(BaseCommand):
    help = "Seed or rotate the singleton system API key from the DJANGO_API_KEY env var."

    def handle(self, *args, **options):
        key = SystemKeyService().seed_from_env(settings.DJANGO_API_KEY)
        if key is None:
            self.stderr.write(
                self.style.WARNING(
                    'DJANGO_API_KEY is blank or the placeholder "none" — no '
                    "system key is active and any earlier one was revoked; "
                    "realtime, crew and chat cannot authenticate to Django. "
                    "Set it to a long random string."
                )
            )
            return
        self.stdout.write(self.style.SUCCESS(f"System API key active (prefix={key.prefix})."))
