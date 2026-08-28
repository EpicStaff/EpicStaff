import getpass
import secrets
import sys

from django.core.management.base import BaseCommand, CommandError

from tables.services.rbac.auth_validation_service import AuthValidationService
from tables.services.rbac.password_recovery_service import PasswordRecoveryService
from tables.services.rbac.rbac_exceptions import (
    FormValidationError,
    UserNotFoundError,
)


class Command(BaseCommand):
    help = (
        "Reset a user's password from the CLI (no-SMTP fallback). "
        "Usage: python manage.py reset_password <email> "
        "[--generate | --password <pw>]. Without a flag, prompts twice for the "
        "new password via getpass. Validates strength using the same "
        "AUTH_PASSWORD_VALIDATORS the HTTP API uses. Invalidates all "
        "outstanding JWT refresh tokens for the user on success."
    )

    _GENERATED_PASSWORD_BYTES = 16

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the user to reset")
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--password",
            help="New password (prefer interactive prompt; this shows in shell history)",
        )
        group.add_argument(
            "--generate",
            action="store_true",
            help="Generate a strong random password and print it once to stdout",
        )

    def handle(self, *args, **options):
        email: str = options["email"]
        new_password = self._resolve_password(options)
        generated = options["generate"]

        validator = AuthValidationService()
        service = PasswordRecoveryService()

        try:
            validator.validate_new_password({"new_password": new_password})
        except FormValidationError as exc:
            raise CommandError(
                "Password validation failed:\n  "
                + "\n  ".join(
                    f"{item['field']}: {item['reason']}" for item in exc.errors
                )
            ) from exc

        try:
            service.cli_reset(email=email, new_password=new_password)
        except UserNotFoundError as exc:
            raise CommandError(f"No user with email '{email}'.") from exc

        self.stdout.write(self.style.SUCCESS(f"Password reset for '{email}'."))
        if generated:
            self.stdout.write(
                self.style.WARNING(f"Generated password (shown once): {new_password}")
            )

    def _resolve_password(self, options) -> str:
        if options["generate"]:
            return secrets.token_urlsafe(self._GENERATED_PASSWORD_BYTES)
        if options["password"]:
            return options["password"]
        if not sys.stdin.isatty():
            raise CommandError(
                "No TTY available; pass --password or --generate explicitly."
            )
        first = getpass.getpass("New password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise CommandError("Passwords do not match.")
        return first
