from django.core.management.base import BaseCommand, CommandError

from rbac.exceptions import FormValidationError
from rbac.identity.reset_user import ResetUserService
from rbac.validation.auth import AuthValidationService


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
        email = options["email"]
        password = options["password"]
        # Validate before the reset deletes every user.
        try:
            AuthValidationService().validate_reset_user({"email": email, "password": password})
        except FormValidationError as exc:
            raise CommandError(
                "Validation failed:\n  "
                + "\n  ".join(
                    f"{field}: {reason}"
                    for field, reasons in exc.field_errors.items()
                    for reason in reasons
                )
            ) from exc

        user = ResetUserService().reset(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created superadmin '{user.email}'."))
