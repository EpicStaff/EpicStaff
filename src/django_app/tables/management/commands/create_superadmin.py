import getpass
import sys

from django.core.management.base import BaseCommand, CommandError

from tables.services.rbac.auth_validation_service import AuthValidationService
from tables.services.rbac.first_setup_service import FirstSetupService
from tables.services.rbac.rbac_exceptions import (
    FormValidationError,
    SetupAlreadyCompletedError,
)


class Command(BaseCommand):
    """Create the first superadmin from the CLI.

    The credential-free counterpart to POST /api/auth/first-setup/, and the
    only creation path when FIRST_SETUP_MODE is `cli_only`. Runs regardless
    of the mode setting.

    This class owns operator I/O only — prompting, argument parsing, exit
    codes. Validation, organization resolution, locking, and user creation
    all live in the service layer, so this path and the HTTP endpoint cannot
    drift apart.
    """

    help = (
        "Create the first superadmin and their default organization. "
        "Prompts for email and password unless --email / --password-stdin "
        "are given. Idempotent: exits 0 with a message if a user already "
        "exists."
    )

    _ALREADY_DONE = "Superadmin already exists - nothing to do."

    # Permits call_command(stdin=...) in tests: Django validates kwargs
    # against the parser's options plus base_stealth_options, and `stdin`
    # is in neither. Django's own createsuperuser does the same.
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            help="Superadmin email address. Prompted for when omitted.",
        )
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help=(
                "Read the password from stdin instead of prompting. Use this "
                "for scripted provisioning; it keeps the password out of the "
                "process list and shell history."
            ),
        )
        parser.add_argument(
            "--org-name",
            help=(
                "Name for the organization created alongside the superadmin. "
                "Ignored when a default organization already exists. "
                "Defaults to settings.DEFAULT_ORGANIZATION_NAME."
            ),
        )

    def handle(self, *args, **options):
        service = FirstSetupService()

        # Checked before prompting: never make an operator type a password
        # that cannot be used.
        if not service.is_setup_required():
            self.stdout.write(self.style.WARNING(self._ALREADY_DONE))
            return

        email = self._resolve_email(options)
        password = self._resolve_password(options)
        org_name = options["org_name"]

        self._validate(email=email, password=password)

        try:
            result = service.setup(email=email, password=password, org_name=org_name)
        except SetupAlreadyCompletedError:
            # Lost a race with a concurrent creator. Same outcome as the
            # pre-flight check above, so report it the same way.
            self.stdout.write(self.style.WARNING(self._ALREADY_DONE))
            return

        if org_name and result.organization.name != org_name:
            self.stdout.write(
                self.style.WARNING(
                    f"--org-name '{org_name}' was ignored: organization "
                    f"'{result.organization.name}' already exists."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created superadmin '{result.user.email}' in organization "
                f"'{result.organization.name}'."
            )
        )

    def _validate(self, email: str, password: str) -> None:
        """Run the same validators the HTTP endpoint runs.

        Raises:
            CommandError: rendered from FormValidationError so the operator
                sees every failing field at once.
        """
        try:
            AuthValidationService().validate_first_setup(
                {"email": email, "password": password}
            )
        except FormValidationError as exc:
            raise CommandError(
                "Validation failed:\n  "
                + "\n  ".join(
                    f"{item['field']}: {item['reason']}" for item in exc.errors
                )
            ) from exc

    def _stream(self, options):
        """stdin to read from.

        Django's `call_command(stdin=...)` does NOT rebind `sys.stdin`; it
        passes the stream through `options`. Honouring it here is what makes
        the command testable without monkeypatching.
        """
        return options.get("stdin") or sys.stdin

    def _resolve_email(self, options) -> str:
        email = options["email"]
        if email:
            return email.strip()
        stream = self._stream(options)
        if not stream.isatty():
            raise CommandError("No TTY available; pass --email explicitly.")
        return input("Email: ").strip()

    def _resolve_password(self, options) -> str:
        stream = self._stream(options)
        if options["password_stdin"]:
            # strip(), not rstrip("\n"): a CRLF pipe (the documented Windows
            # flow) leaves a trailing \r that rstrip("\n") wouldn't touch,
            # and PrintableAsciiPasswordValidator rejects it as whitespace.
            # Stripping both ends is safe since that same validator already
            # rejects any password containing whitespace.
            password = stream.readline().strip()
            if not password:
                raise CommandError("No password received on stdin.")
            return password
        if not stream.isatty():
            raise CommandError("No TTY available; pass --password-stdin explicitly.")
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise CommandError("Passwords do not match.")
        return first
