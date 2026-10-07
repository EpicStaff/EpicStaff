from functools import partial

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from loguru import logger

from rbac.exceptions import (
    InvalidOrExpiredTokenError,
    SuperadminRequiredError,
    UserNotFoundError,
)
from rbac.identity.credential_revocation import (
    CredentialRevocationService,
)
from rbac.identity.passwords import reset_dispatcher
from rbac.identity.passwords.email_sender import (
    PasswordResetEmailSender,
)
from rbac.identity.passwords.reset_dispatcher import (
    PasswordResetDispatcher,
)
from rbac.identity.passwords.smtp_config import SmtpConfigService
from rbac.identity.passwords.token_repository import (
    PasswordResetTokenRepository,
)
from rbac.identity.passwords.writer import PasswordWriter

_SMTP_OFF_LOG_CACHE_KEY = "rbac:password_reset:smtp_off_logged"
_SMTP_OFF_LOG_INTERVAL_SECONDS = 300


class PasswordRecoveryService:
    """Orchestrator for password-recovery flows.

    The only service view code talks to. Composes small single-purpose
    collaborators (token repo, email sender, credential revoker,
    password writer, smtp detector) so each concern is swappable in
    tests and so the orchestrator itself stays short and auditable.

    Security invariants enforced here (not in views, not in
    serializers):
      - Anonymous request flow never reveals whether the email exists,
        neither in its response nor in its timing: the request only queues
        a job, and everything that depends on the account runs on the
        dispatcher's worker thread.
      - Without SMTP the anonymous request flow issues no token at all;
        recovery is the operator's `manage.py reset_password`.
      - Prior reset tokens for a user are invalidated as soon as a new
        one is issued (only the latest link works).
      - Tokens are single-use and time-bound; the repo filters on both
        before handing a token back.
      - Any successful password change — via reset, self-service, admin
        reset, or CLI — blacklists every live refresh token and revokes
        every personal API key the affected user holds at that moment, in
        the same transaction as the password write. Every access and
        refresh token minted before the change is rejected through the
        password binding (`CHECK_REVOKE_TOKEN`); the blacklisting is
        defence in depth.
      - Admin reset is gated on `actor.is_superadmin`.
      - Every flow checks the new password against the target account
        (`PasswordWriter.set`) before writing anything; a rejection raises
        FormValidationError and the transaction changes nothing.
    """

    def __init__(
        self,
        token_repo: PasswordResetTokenRepository | None = None,
        email_sender: PasswordResetEmailSender | None = None,
        credential_revoker: CredentialRevocationService | None = None,
        password_writer: PasswordWriter | None = None,
        smtp_config: SmtpConfigService | None = None,
        dispatcher: PasswordResetDispatcher | None = None,
    ):
        self._token_repo = token_repo or PasswordResetTokenRepository()
        self._email_sender = email_sender or PasswordResetEmailSender()
        self._credential_revoker = credential_revoker or CredentialRevocationService()
        self._password_writer = password_writer or PasswordWriter()
        self._smtp_config = smtp_config or SmtpConfigService()
        self._dispatcher = dispatcher

    # ---- anonymous flow ----

    def request_reset(self, email: str) -> dict:
        """Queue a reset link for `email`, if SMTP is configured.

        The request does the same fixed work for every email: it queues
        `deliver_reset` on the dispatcher and returns. Looking the account up,
        writing the token and the SMTP round trip all happen on a worker
        thread, so neither the response nor its timing reveals whether the
        email has an account. Delivery is best-effort: a job dropped because
        the backlog is full, or lost with its worker process, sends nothing,
        and the user asks again.

        Without SMTP the request is ignored and nothing is queued: no token is
        issued, prior grants are left alone and nothing is sent. The only
        channel a link could take is then the console mail backend, which
        writes it to the application log, readable by anyone with log access.
        Operators reset passwords with `manage.py reset_password` instead.

        Returns:
            `{"smtp_configured": bool}` — identical for every email, so the
            response never reveals whether an account exists.
        """
        if not self._smtp_config.is_configured():
            self._log_request_ignored_without_smtp()
            return {"smtp_configured": False}
        # Resolved per call, not in `__init__`: views build this service once,
        # at import, and the process has one shared dispatcher.
        dispatcher = self._dispatcher or reset_dispatcher.default_dispatcher
        dispatcher.dispatch(partial(self.deliver_reset, email))
        return {"smtp_configured": True}

    def deliver_reset(self, email: str) -> None:
        """Issue a fresh reset grant for the account of `email` and mail its link.

        Runs on a dispatcher worker thread, never in the request. Does nothing
        when no account has this email (matched case-insensitively). Every
        prior grant of the account is deleted in the same transaction that
        creates the new one, so only the newest link works. The account row
        is locked for that transaction: two jobs for the same email run one
        after the other, and the second deletes the first one's grant.
        """
        with transaction.atomic():
            user = self._find_user_by_email(email, lock=True)
            if user is None:
                return
            self._token_repo.invalidate_all_for_user(user)
            _token_row, raw_token = self._token_repo.create_for_user(user)
        # Sent after the commit, so a slow SMTP server cannot hold the token
        # rows locked, and the link never points at a grant that was rolled
        # back.
        self._email_sender.send(user, raw_token)

    def confirm_reset(self, raw_token: str, new_password: str) -> None:
        token_row = self._token_repo.get_active_by_raw_token(raw_token)
        if token_row is None:
            raise InvalidOrExpiredTokenError()
        user = token_row.user
        with transaction.atomic():
            # The writer validates against the account before any write, so a
            # rejected password leaves the token unspent for a retry.
            self._password_writer.set(user, new_password)
            self._token_repo.consume(token_row)
            self._credential_revoker.revoke_all_credentials_for_user(user)

    # ---- admin flow ----

    def admin_reset(self, actor, target_user_id: int, new_password: str) -> None:
        if not getattr(actor, "is_superadmin", False):
            raise SuperadminRequiredError()
        target = self._get_user_by_id(target_user_id)
        with transaction.atomic():
            self._password_writer.set(target, new_password)
            self._token_repo.invalidate_all_for_user(target)
            self._credential_revoker.revoke_all_credentials_for_user(target)

    # ---- CLI flow ----

    def cli_reset(self, email: str, new_password: str) -> None:
        user = self._find_user_by_email(email)
        if user is None:
            raise UserNotFoundError()
        with transaction.atomic():
            self._password_writer.set(user, new_password)
            self._token_repo.invalidate_all_for_user(user)
            self._credential_revoker.revoke_all_credentials_for_user(user)

    # ---- helpers ----

    @staticmethod
    def _log_request_ignored_without_smtp() -> None:
        # The endpoint is anonymous and its throttle is keyed on ip|email, so
        # rotating emails gets a fresh bucket per request. `cache.add` is an
        # atomic set-if-absent shared by every worker: one line per window,
        # however many requests arrive.
        if not cache.add(_SMTP_OFF_LOG_CACHE_KEY, True, timeout=_SMTP_OFF_LOG_INTERVAL_SECONDS):
            return
        # Kept under the 200-character cut of `utils.logger`'s stdout sink.
        logger.warning(
            "password_reset_request_ignored_smtp_not_configured: set "
            "DJANGO_EMAIL_HOST to enable self-service reset, or run "
            "`manage.py reset_password <email>`. Repeats suppressed for {}s.",
            _SMTP_OFF_LOG_INTERVAL_SECONDS,
        )

    # ---- lookup helpers ----

    @staticmethod
    def _find_user_by_email(email: str, lock: bool = False):
        User = get_user_model()  # noqa: N806
        users = User.objects.select_for_update() if lock else User.objects
        return users.filter(email__iexact=email).first()

    @staticmethod
    def _get_user_by_id(user_id: int):
        User = get_user_model()  # noqa: N806
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise UserNotFoundError()
        return user
