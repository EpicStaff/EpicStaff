import pytest
from django.core import mail
from django.test import override_settings

from rbac.identity.passwords.email_sender import PasswordResetEmailSender
from utils.logger import logger

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"
CONSOLE_EMAIL = "django.core.mail.backends.console.EmailBackend"
RAW_TOKEN = "RAW_RESET_TOKEN_MARKER_must_not_leak"


@pytest.fixture
def captured_log_messages():
    """Collect every loguru message emitted while the test runs, at every level."""
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", format="{message}")
    yield messages
    logger.remove(sink_id)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_sender_mails_the_reset_link_when_smtp_is_configured(regular_user):
    mail.outbox = []

    PasswordResetEmailSender().send(regular_user, RAW_TOKEN)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [regular_user.email]
    assert f"token={RAW_TOKEN}" in mail.outbox[0].body


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_sender_drops_the_reset_link_when_smtp_is_not_configured(
    regular_user, captured_log_messages
):
    mail.outbox = []

    PasswordResetEmailSender().send(regular_user, RAW_TOKEN)

    assert mail.outbox == []
    assert any(
        "password_reset_email_not_sent_smtp_not_configured" in message
        for message in captured_log_messages
    )
    assert not any(RAW_TOKEN in message for message in captured_log_messages)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=CONSOLE_EMAIL, EMAIL_HOST="")
def test_sender_never_prints_the_reset_link_through_the_console_backend(
    regular_user, capsys, captured_log_messages
):
    PasswordResetEmailSender().send(regular_user, RAW_TOKEN)

    stdout, stderr = capsys.readouterr()
    assert RAW_TOKEN not in stdout
    assert RAW_TOKEN not in stderr
    assert not any(RAW_TOKEN in message for message in captured_log_messages)
