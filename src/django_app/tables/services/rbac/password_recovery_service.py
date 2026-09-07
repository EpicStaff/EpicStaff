from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction

from tables.services.rbac.rbac_exceptions import (
    InvalidOrExpiredTokenError,
    SuperadminRequiredError,
    UserNotFoundError,
)
from tables.services.rbac.utils.password_reset_email_sender import (
    PasswordResetEmailSender,
)
from tables.services.rbac.utils.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from tables.services.rbac.utils.password_writer import PasswordWriter
from tables.services.rbac.utils.session_invalidation_service import (
    SessionInvalidationService,
)
from tables.services.rbac.utils.smtp_config_service import SmtpConfigService


class PasswordRecoveryService:
    """Orchestrator for password-recovery flows.

    The only service view code talks to. Composes small single-purpose
    collaborators (token repo, email sender, session invalidator,
    password writer, smtp detector) so each concern is swappable in
    tests and so the orchestrator itself stays short and auditable.

    Security invariants enforced here (not in views, not in
    serializers):
      - Anonymous request flow never reveals whether the email exists.
      - Prior reset tokens for a user are invalidated as soon as a new
        one is issued (only the latest link works).
      - Tokens are single-use and time-bound; the repo filters on both
        before handing a token back.
      - Any successful password change — via reset, self-service, admin
        reset, or CLI — blacklists every outstanding refresh token for
        the affected user.
      - Admin reset is gated on `actor.is_superadmin`.
    """

    def __init__(
        self,
        token_repo: Optional[PasswordResetTokenRepository] = None,
        email_sender: Optional[PasswordResetEmailSender] = None,
        session_invalidator: Optional[SessionInvalidationService] = None,
        password_writer: Optional[PasswordWriter] = None,
        smtp_config: Optional[SmtpConfigService] = None,
    ):
        self._token_repo = token_repo or PasswordResetTokenRepository()
        self._email_sender = email_sender or PasswordResetEmailSender()
        self._session_invalidator = session_invalidator or SessionInvalidationService()
        self._password_writer = password_writer or PasswordWriter()
        self._smtp_config = smtp_config or SmtpConfigService()

    # ---- anonymous flow ----

    def request_reset(self, email: str) -> dict:
        smtp_configured = self._smtp_config.is_configured()
        user = self._find_user_by_email(email)
        if user is not None:
            with transaction.atomic():
                self._token_repo.invalidate_all_for_user(user)
                _token_row, raw_token = self._token_repo.create_for_user(user)
            # Email dispatch is outside the transaction so a slow/blocked
            # SMTP server cannot hold a DB row lock. The sender swallows
            # its own failures — the HTTP response stays uniform.
            self._email_sender.send(user, raw_token)
        return {"smtp_configured": smtp_configured}

    def confirm_reset(self, raw_token: str, new_password: str) -> None:
        token_row = self._token_repo.get_active_by_raw_token(raw_token)
        if token_row is None:
            raise InvalidOrExpiredTokenError()
        user = token_row.user
        with transaction.atomic():
            self._password_writer.set(user, new_password)
            self._token_repo.consume(token_row)
        self._session_invalidator.blacklist_all_for_user(user)

    # ---- admin flow ----

    def admin_reset(self, actor, target_user_id: int, new_password: str) -> None:
        if not getattr(actor, "is_superadmin", False):
            raise SuperadminRequiredError()
        target = self._get_user_by_id(target_user_id)
        with transaction.atomic():
            self._password_writer.set(target, new_password)
            self._token_repo.invalidate_all_for_user(target)
        self._session_invalidator.blacklist_all_for_user(target)

    # ---- CLI flow ----

    def cli_reset(self, email: str, new_password: str) -> None:
        user = self._find_user_by_email(email)
        if user is None:
            raise UserNotFoundError()
        with transaction.atomic():
            self._password_writer.set(user, new_password)
            self._token_repo.invalidate_all_for_user(user)
        self._session_invalidator.blacklist_all_for_user(user)

    # ---- lookup helpers ----

    @staticmethod
    def _find_user_by_email(email: str):
        User = get_user_model()
        return User.objects.filter(email__iexact=email).first()

    @staticmethod
    def _get_user_by_id(user_id: int):
        User = get_user_model()
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise UserNotFoundError()
        return user
