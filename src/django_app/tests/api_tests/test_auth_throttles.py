"""Per-IP throttles on the two anonymous auth endpoints that had none.

Both `POST /api/auth/refresh/` and `POST /api/auth/password-reset/confirm/` are
`AllowAny` with `authentication_classes = []`, so before these throttles an
attacker could hammer them unmetered — replaying a stolen refresh cookie, or
churning guesses at a live reset token.

Both key on IP alone, deliberately. Refresh carries no caller-supplied
identifier at all (the token is in an HttpOnly cookie). Confirm carries exactly
one — the token — which is the value an attacker varies, so bucketing by it
would hand out a fresh allowance per guess and throttle nothing.

The login/reset-request throttles, which key on a composite `ip|email`, are
covered in test_rbac_auth.py.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse


@pytest.mark.django_db
def test_password_reset_confirm_is_throttled_per_ip(api_client):
    cache.clear()
    url = reverse("password_reset_confirm")
    payload = {"token": "not-a-real-token", "new_password": "BrandNewPass123!"}
    for _ in range(10):  # password_reset_confirm scope: 10/hour
        assert api_client.post(url, data=payload, format="json").status_code == 400
    r = api_client.post(url, data=payload, format="json")
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.django_db
def test_token_refresh_is_throttled_per_ip(api_client):
    """No cookie means 401 every time, but the throttle must still fire —
    the point is bounding attempts, not the outcome of any one attempt."""
    cache.clear()
    url = reverse("refresh")
    for _ in range(30):  # token_refresh scope: 30/min
        assert api_client.post(url).status_code == 401
    r = api_client.post(url)
    assert r.status_code == 429
