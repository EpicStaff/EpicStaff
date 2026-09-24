from django.conf import settings


class SmtpConfigService:
    """Answers a single question: is SMTP delivery configured in this env?

    "Configured" means `EMAIL_HOST` is set to a non-empty string. That is
    the only signal that distinguishes a real outbound relay from the
    console fallback backend. Whether the relay also requires
    authentication (USER + PASSWORD) is an orthogonal concern — some
    relays (mailpit, local Postfix, corporate MTAs) accept mail without
    AUTH, so we must not conflate "has credentials" with "is configured".

    Callers use this to decide whether to advertise email delivery to
    the end user. They must not inspect `EMAIL_BACKEND` directly.
    """

    def is_configured(self) -> bool:
        return bool(getattr(settings, "EMAIL_HOST", ""))
