"""Per-IP throttles on the two anonymous auth endpoints that had none:
`POST /api/auth/refresh/` and `POST /api/auth/password-reset/confirm/`.

The login/reset-request throttles (composite `ip|email`) live in
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
from django.urls import reverse

from tables.throttles import PasswordResetConfirmThrottle, TokenRefreshThrottle

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
