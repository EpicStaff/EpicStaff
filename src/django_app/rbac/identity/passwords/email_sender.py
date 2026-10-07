import traceback
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from utils.logger import logger

from rbac.identity.passwords.smtp_config import SmtpConfigService


class PasswordResetEmailSender:
    """Renders and dispatches the password-reset email.

    The sender is intentionally fail-silent. It runs on a
    `PasswordResetDispatcher` worker, after the request has returned, so
    nothing upstream could act on an SMTP error. The failure is logged by
    user id, exception type and location only, so operators can still see
    it without the log ever holding the email address or the link.

    The email carries a live credential, so it is only handed to a real
    SMTP relay. When `SmtpConfigService` reports SMTP as not configured,
    Django's backend is the console one, which would write the link into
    the application log; the sender then drops the message without
    rendering it. `PasswordRecoveryService` already skips issuing a token
    in that case — this check keeps any other caller from leaking a link.
    """

    _SUBJECT_TEMPLATE = "rbac/password_reset_email.subject.txt"
    _BODY_TEMPLATE = "rbac/password_reset_email.txt"

    def __init__(self, smtp_config: SmtpConfigService | None = None):
        self._smtp_config = smtp_config or SmtpConfigService()

    def send(self, user, raw_token: str) -> None:
        if not self._smtp_config.is_configured():
            logger.warning(
                "password_reset_email_not_sent_smtp_not_configured user_id={}",
                user.id,
            )
            return
        try:
            context = self._build_context(user, raw_token)
            subject = render_to_string(self._SUBJECT_TEMPLATE, context).strip()
            body = render_to_string(self._BODY_TEMPLATE, context)
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as error:
            # Not `logger.exception`: loguru prints a traceback with the value
            # of every local, and the error message itself (a refused
            # recipient, for one) can name the address. Both would put the
            # email, and the raw token, into the application log.
            failed_at = traceback.extract_tb(error.__traceback__)[-1]
            logger.error(
                "password_reset_email_send_failed user_id={} error_type={} at={}:{} in {}",
                user.id,
                type(error).__name__,
                failed_at.filename,
                failed_at.lineno,
                failed_at.name,
            )

    def _build_context(self, user, raw_token: str) -> dict:
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        path = settings.FRONTEND_PASSWORD_RESET_PATH
        if not path.startswith("/"):
            path = "/" + path
        query = urlencode({"token": raw_token})
        reset_link = f"{base}{path}?{query}"
        ttl_minutes = max(1, int(settings.PASSWORD_RESET_TOKEN_TTL) // 60)
        return {
            "email": user.email,
            "display_name": getattr(user, "display_name", None),
            "reset_link": reset_link,
            "ttl_minutes": ttl_minutes,
        }
