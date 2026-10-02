from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from loguru import logger


class PasswordResetEmailSender:
    """Renders and dispatches the password-reset email.

    The sender is intentionally fail-silent: a downstream SMTP error must
    not change the HTTP response of `POST /password-reset/request/`,
    because that response is uniform by design (no enumeration). The
    failure is logged so operators can still see it.

    Delivery goes through Django's configured `EMAIL_BACKEND`. In dev
    (no SMTP creds) that is the console backend and the link lands in
    stdout, which is the documented no-SMTP recovery path.
    """

    _SUBJECT_TEMPLATE = "rbac/password_reset_email.subject.txt"
    _BODY_TEMPLATE = "rbac/password_reset_email.txt"

    def send(self, user, raw_token: str) -> None:
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
        except Exception:
            logger.exception("password_reset_email_send_failed user_id={}", user.id)

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
