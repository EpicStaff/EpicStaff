"""
Tests for POST /api/notify/email/ (EST-3285 item 4.8: notification_tool,
channel='email'). Uses Django's mail test outbox (console/locmem backend)
rather than mocking send_mail directly, since that's the standard Django way
to assert on dispatched mail without touching a real SMTP server.
"""

from unittest.mock import patch

import pytest

from django.core import mail
from django.urls import reverse
from rest_framework import status

from tables.throttles import NotifyEmailThrottle
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


@pytest.mark.django_db
def test_throttle_blocks_after_limit_and_sends_no_mail(auth_client, monkeypatch):
    """NotifyEmailThrottle caps how many notification emails a single
    authenticated user can send per window (review finding: the endpoint had
    no throttling and was usable as an authenticated mail relay -- any
    prompt-injected agent or leaked API key could otherwise spam unlimited
    external addresses via notification_tool).

    `SimpleRateThrottle.THROTTLE_RATES` is read from DRF's `api_settings` once
    at class-definition time, so `override_settings` on `REST_FRAMEWORK` does
    NOT retroactively change it -- monkeypatching the class attribute directly
    is the reliable way to shrink the rate for this test without needing 10
    real calls against the production default. `send_mail` is mocked directly
    (rather than relying on the mailoutbox fixture used by the tests above) so
    we can assert it is never invoked once the throttle trips."""
    monkeypatch.setattr(
        NotifyEmailThrottle, "THROTTLE_RATES", {"notify_email": "2/hour"}
    )

    with patch(
        "tables.services.notification_email_sender.send_mail"
    ) as mock_send_mail:
        for _ in range(2):
            resp = auth_client.post(
                _url(),
                {"to": "ops@example.com", "message": "Build is done."},
                format="json",
            )
            assert resp.status_code == status.HTTP_200_OK, resp.content

        resp = auth_client.post(
            _url(),
            {"to": "ops@example.com", "message": "Build is done."},
            format="json",
        )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Retry-After" in resp.headers
        assert mock_send_mail.call_count == 2
