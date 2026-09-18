from django.conf import settings
from django.core.mail import send_mail
from loguru import logger


class NotificationEmailSender:
    """Sends a plain-text agent-triggered notification email.

    Delivers via Django's configured `send_mail` / `EMAIL_BACKEND` -- the
    SAME transport `PasswordResetEmailSender` uses (see
    tables/services/rbac/utils/password_reset_email_sender.py). Reusing it
    here (rather than writing a parallel SMTP client) keeps exactly one place
    in the codebase talking to the mail transport, so SMTP config/creds only
    ever live in one spot.

    Unlike PasswordResetEmailSender this is NOT fail-silent: the caller
    (NotifyEmailView, called by notification_tool over REST) needs to know
    whether delivery succeeded so it can report a readable error back to the
    calling agent instead of silently swallowing an SMTP failure.
    """

    def send(self, to: str, subject: str, message: str) -> tuple[bool, str | None]:
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to],
                fail_silently=False,
            )
            return True, None
        except Exception as e:
            logger.exception(f"notification_email_send_failed to={to}")
            return False, str(e)
