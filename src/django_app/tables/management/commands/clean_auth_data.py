from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from tables.models.rbac_models import ApiKey, Organization


class Command(BaseCommand):
    help = (
        "Dev-only: wipe all Users, Organizations, and ApiKeys so that "
        "POST /api/auth/first-setup/ reopens on a clean slate. Useful for FE "
        "devs testing the first-setup flow without dropping the whole DB. "
        "Built-in Roles and RolePermissions are preserved."
    )

    def handle(self, *args, **options):
        user_model = get_user_model()

        with transaction.atomic():
            user_count = user_model.objects.count()
            org_count = Organization.objects.count()
            key_count = ApiKey.objects.count()

            user_model.objects.all().delete()
            Organization.objects.all().delete()
            ApiKey.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {user_count} user(s), {org_count} organization(s), "
                f"{key_count} API key(s). First-setup is now reopen."
            )
        )
