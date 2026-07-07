"""
Tests for POST /api/notify/email/ (EST-3285 item 4.8: notification_tool,
channel='email'). Uses Django's mail test outbox (console/locmem backend)
rather than mocking send_mail directly, since that's the standard Django way
to assert on dispatched mail without touching a real SMTP server.
"""

import pytest

from django.core import mail
from django.urls import reverse
from rest_framework import status

from tests.fixtures import *  # noqa: F401,F403


def _url():
    return reverse("notify-email")


@pytest.mark.django_db
def test_sends_email_and_returns_200(auth_client, mailoutbox):
    response = auth_client.post(
        _url(),
        {"to": "ops@example.com", "subject": "Heads up", "message": "Build is done."},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["sent"] is True
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["ops@example.com"]
    assert sent.subject == "Heads up"
    assert sent.body == "Build is done."


@pytest.mark.django_db
def test_defaults_subject_when_not_supplied(auth_client, mailoutbox):
    response = auth_client.post(
        _url(),
        {"to": "ops@example.com", "message": "Build is done."},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert mail.outbox[0].subject == "EpicStaff notification"


@pytest.mark.django_db
def test_invalid_email_address_rejected(auth_client, mailoutbox):
    response = auth_client.post(
        _url(),
        {"to": "not-an-email", "message": "Build is done."},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_missing_message_rejected(auth_client, mailoutbox):
    response = auth_client.post(
        _url(),
        {"to": "ops@example.com"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_unauthenticated_request_still_sends_via_default_permission(
    api_client, mailoutbox
):
    """NotifyEmailView relies purely on DRF's global default
    IsAuthenticated permission (no view-level ownership check like the
    decision endpoints -- there's no per-org resource here, just "does the
    caller hold a valid API key/JWT at all"). `tests/settings.py` disables
    DRF auth/permission enforcement for the whole suite (see
    wait_for_decision_endpoints_test.py's module docstring for why), so in
    THIS test environment the request reaches the view regardless of
    credentials -- in production, IsAuthenticated would return 401 before
    the view ever runs."""
    response = api_client.post(
        _url(),
        {"to": "ops@example.com", "message": "Build is done."},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
