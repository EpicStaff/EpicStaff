from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tables.models.auth_models import ApiKey


class Command(BaseCommand):
    help = "Delete all users and API keys, then create a new superuser with a fresh API key"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="New superuser username")
        parser.add_argument("--password", required=True, help="New superuser password")
        parser.add_argument("--email", default="", help="New superuser email (optional)")

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]
        email = options["email"]

        user_model = get_user_model()

        user_count = user_model.objects.count()
        key_count = ApiKey.objects.count()
        user_model.objects.all().delete()
        ApiKey.objects.all().delete()
        self.stdout.write(f"Deleted {user_count} user(s) and {key_count} API key(s).")

        user_model.objects.create_superuser(username=username, password=password, email=email)

        raw_key = ApiKey.generate_raw_key()
        key = ApiKey(name="realtime-default")
        key.set_key(raw_key)
        key.save()

        self.stdout.write(self.style.SUCCESS(f"Created superuser '{username}'."))
        self.stdout.write(self.style.SUCCESS(f"API key: {raw_key}"))
