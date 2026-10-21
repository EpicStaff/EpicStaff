from django.conf import settings
from django.core.mail import get_connection

SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def test_smtp_backend_gives_up_on_a_silent_relay():
    """Without a timeout, a relay that never answers hangs the password-reset
    worker threads for good. The SMTP backend must pick the setting up."""
    assert settings.EMAIL_TIMEOUT > 0
    assert get_connection(SMTP_BACKEND).timeout == settings.EMAIL_TIMEOUT
