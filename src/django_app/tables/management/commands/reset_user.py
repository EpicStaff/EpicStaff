from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tables.models.rbac_models import ApiKey


class Command(BaseCommand):
    help = (
        "Delete all users and API keys, then create a new superuser with a fresh "
        "API key. NOTE: uses email (USERNAME_FIELD) instead of username. "
        "Will be rebuilt in Story 2/5 to wrap in "
        "transaction.atomic() and also create the default Organization + "
        "OrganizationUser for the new superadmin."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="New superuser email")
        parser.add_argument("--password", required=True, help="New superuser password")

    def handle(self, *args, **options):
        email = options["email"]
        password = options["password"]

        user_model = get_user_model()

        user_count = user_model.objects.count()
        key_count = ApiKey.objects.count()
        user_model.objects.all().delete()
        ApiKey.objects.all().delete()
        self.stdout.write(f"Deleted {user_count} user(s) and {key_count} API key(s).")

        user = user_model.objects.create_superuser(email=email, password=password)

        raw_key = ApiKey.generate_raw_key()
        key = ApiKey(name="realtime-default", created_by=user)
        key.set_key(raw_key)
        key.save()

        self.stdout.write(self.style.SUCCESS(f"Created superuser '{email}'."))
        self.stdout.write(self.style.SUCCESS(f"API key: {raw_key}"))
