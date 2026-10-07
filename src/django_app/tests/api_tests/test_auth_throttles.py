"""Per-IP throttles on the anonymous auth endpoints:
`POST /api/auth/refresh/`, `POST /api/auth/password-reset/confirm/`, and the
IP-only cap on `POST /api/auth/password-reset/request/`.

The login/reset-request throttles keyed on `ip|email` live in
test_rbac_auth.py.

Rates are pinned by patching the throttle's `rate` attribute, not with
override_settings: DRF binds SimpleRateThrottle.THROTTLE_RATES at class
definition time, so overriding REST_FRAMEWORK has no effect on it. Setting
`rate` works because SimpleRateThrottle.__init__ skips get_rate() when the
attribute is already set.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from rbac.models import PasswordResetToken
from rbac.throttles import (
    PasswordResetConfirmThrottle,
    PasswordResetRequestIpThrottle,
    TokenRefreshThrottle,
)

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"

CONFIRM_PAYLOAD = {"token": "not-a-real-token", "new_password": "BrandNewPass123!"}


@pytest.mark.django_db
@patch.object(PasswordResetConfirmThrottle, "rate", "2/hour", create=True)
def test_password_reset_confirm_is_throttled(api_client):
    cache.clear()
    url = reverse("password_reset_confirm")

    for _ in range(2):
        assert (
            api_client.post(url, data=CONFIRM_PAYLOAD, format="json").status_code == 400
        )

    r = api_client.post(url, data=CONFIRM_PAYLOAD, format="json")
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.django_db
@patch.object(TokenRefreshThrottle, "rate", "2/min", create=True)
def test_token_refresh_is_throttled(api_client):
    # No cookie means 401 every time; the throttle still has to fire.
    cache.clear()
    url = reverse("refresh")

    for _ in range(2):
        assert api_client.post(url).status_code == 401

    r = api_client.post(url)
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.django_db
@patch.object(PasswordResetConfirmThrottle, "rate", "2/hour", create=True)
def test_confirm_throttle_ignores_a_forged_forwarded_for(api_client):
    """A client-supplied X-Forwarded-For must not mint a fresh bucket.

    nginx appends its own `$remote_addr` to whatever the client sent, so with
    NUM_PROXIES=1 DRF reads only that last entry. Deliberately does not patch
    NUM_PROXIES - this guards the production setting.
    """
    cache.clear()
    url = reverse("password_reset_confirm")

    for i in range(2):
        r = api_client.post(
            url,
            data=CONFIRM_PAYLOAD,
            format="json",
            HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 127.0.0.1",
        )
        assert r.status_code == 400

    r = api_client.post(
        url,
        data=CONFIRM_PAYLOAD,
        format="json",
        HTTP_X_FORWARDED_FOR="10.0.0.99, 127.0.0.1",
    )
    assert r.status_code == 429


# ---------------- password-reset request: per-IP cap ----------------

RESET_REQUEST_IP_RATE = "3/hour"
FROZEN_NOW = 1_000_000.0


def _request_reset(api_client, email, **extra):
    return api_client.post(
        reverse("password_reset_request"), data={"email": email}, format="json", **extra
    )


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@patch.object(PasswordResetRequestIpThrottle, "rate", RESET_REQUEST_IP_RATE, create=True)
def test_reset_request_from_one_ip_rotating_emails_is_throttled(api_client):
    """Each email is a fresh `ip|email` bucket; only the IP cap stops this."""
    cache.clear()

    for index in range(3):
        assert _request_reset(api_client, f"probe{index}@example.com").status_code == 200

    r = _request_reset(api_client, "probe-next@example.com")
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@patch.object(PasswordResetRequestIpThrottle, "rate", RESET_REQUEST_IP_RATE, create=True)
@patch.object(PasswordResetRequestIpThrottle, "timer", staticmethod(lambda: FROZEN_NOW))
def test_reset_request_ip_throttle_answers_alike_for_registered_and_unknown_emails(
    api_client, regular_user
):
    # The clock is frozen so both 429s carry the same "available in N seconds".
    cache.clear()
    for index in range(3):
        _request_reset(api_client, f"probe{index}@example.com")
    PasswordResetToken.objects.all().delete()

    registered = _request_reset(api_client, regular_user.email)
    unknown = _request_reset(api_client, "nobody@example.com")

    assert registered.status_code == unknown.status_code == 429
    assert registered.json() == unknown.json()
    assert registered.headers["Retry-After"] == unknown.headers["Retry-After"]
    # Throttled before the view, so no job ran for the registered email.
    assert PasswordResetToken.objects.count() == 0


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@patch.object(PasswordResetRequestIpThrottle, "rate", RESET_REQUEST_IP_RATE, create=True)
def test_reset_request_ip_throttle_leaves_other_ips_alone(api_client):
    cache.clear()
    for index in range(3):
        _request_reset(api_client, f"probe{index}@example.com", REMOTE_ADDR="10.0.0.1")
    assert (
        _request_reset(api_client, "probe-next@example.com", REMOTE_ADDR="10.0.0.1").status_code
        == 429
    )

    r = _request_reset(api_client, "someone@example.com", REMOTE_ADDR="10.0.0.2")

    assert r.status_code == 200


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
@patch.object(PasswordResetRequestIpThrottle, "rate", RESET_REQUEST_IP_RATE, create=True)
def test_reset_request_ip_throttle_ignores_a_forged_forwarded_for(api_client):
    """Same production NUM_PROXIES guard as the confirm throttle above."""
    cache.clear()
    for index in range(3):
        _request_reset(
            api_client,
            f"probe{index}@example.com",
            HTTP_X_FORWARDED_FOR=f"10.0.0.{index}, 127.0.0.1",
        )

    r = _request_reset(
        api_client, "probe-next@example.com", HTTP_X_FORWARDED_FOR="10.0.0.99, 127.0.0.1"
    )

    assert r.status_code == 429
