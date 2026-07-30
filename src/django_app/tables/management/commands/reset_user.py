from django.core.management.base import BaseCommand

from tables.services.rbac.reset_user_service import ResetUserService


class Command(BaseCommand):
    help = (
        "Delete all users (their API keys cascade), then create a fresh "
        "superadmin with a default-org membership. The system API key is "
        "preserved. Create personal API keys via POST /api/profile/api-keys/."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="New superadmin email")
        parser.add_argument("--password", required=True, help="New superadmin password")

    def handle(self, *args, **options):
        service = ResetUserService()
        user = service.reset(email=options["email"], password=options["password"])
        self.stdout.write(self.style.SUCCESS(f"Created superadmin '{user.email}'."))
