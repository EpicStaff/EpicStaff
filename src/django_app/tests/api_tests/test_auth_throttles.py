"""Per-IP throttles on the anonymous auth endpoints:
`POST /api/auth/refresh/`, `POST /api/auth/password-reset/confirm/`, and the
IP-only cap on `POST /api/auth/password-reset/request/`.

The login/reset-request throttles keyed on `ip|email` live in
test_rbac_auth.py; this file keeps the forged-forwarding-header guards for
all of them.

Rates are pinned by patching the throttle's `rate` attribute, not with
override_settings: DRF binds SimpleRateThrottle.THROTTLE_RATES at class
definition time, so overriding REST_FRAMEWORK has no effect on it. Setting
`rate` works because SimpleRateThrottle.__init__ skips get_rate() when the
attribute is already set.
"""

import asyncio
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.core.signals import request_finished, request_started
from django.db import close_old_connections
from django.test import override_settings
from django.urls import reverse

from django_app.asgi import application, django_asgi_app
from rbac.models import PasswordResetToken
from rbac.throttles import (
    LoginThrottle,
    PasswordResetConfirmThrottle,
    PasswordResetRequestIpThrottle,
    TokenRefreshThrottle,
)

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"

CONFIRM_PAYLOAD = {"token": "not-a-real-token", "new_password": "BrandNewPass123!"}


def one_trusted_proxy():
    """Pin NUM_PROXIES to the bundled nginx, independent of the local `.env`.

    DRF reloads `api_settings` on `setting_changed`, and `get_ident()` reads
    NUM_PROXIES on every call, so the override reaches the throttles.
    """
    return override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1})


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
@one_trusted_proxy()
@patch.object(PasswordResetConfirmThrottle, "rate", "2/hour", create=True)
def test_confirm_throttle_ignores_a_forged_forwarded_for(api_client):
    """A client-supplied X-Forwarded-For must not mint a fresh bucket.

    nginx appends its own `$remote_addr` to whatever the client sent, so with
    NUM_PROXIES=1 (one nginx, the shipped default) DRF reads only that last
    entry. A larger NUM_PROXIES would read the forged entry and fail this test.
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
@one_trusted_proxy()
@patch.object(PasswordResetRequestIpThrottle, "rate", RESET_REQUEST_IP_RATE, create=True)
def test_reset_request_ip_throttle_ignores_a_forged_forwarded_for(api_client):
    """Same NUM_PROXIES=1 forged-entry guard as the confirm throttle above."""
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


# ---------------- underscore spelling of X-Forwarded-For, over ASGI ----------------
#
# The Django test client builds META directly, so it cannot send both
# `X-Forwarded-For` and `X_Forwarded_For`: both are already HTTP_X_FORWARDED_FOR
# there. The merge that lets a caller pick its throttle identity happens when
# Django's ASGI handler builds META from scope headers, so these tests drive the
# ASGI application itself.

LOGIN_BODY = b'{"email": "asgi-probe@example.com", "password": "wrong-password"}'


@pytest.fixture
def keep_test_db_connection_open():
    """Stop the ASGI handler's request signals from closing the test's DB connection.

    The Django test client does the same; calling the ASGI app directly does not.
    """
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    yield
    request_started.connect(close_old_connections)
    request_finished.connect(close_old_connections)


def _login_over_asgi(asgi_app, forged_address):
    """POST a failed login as nginx would forward it, plus a forged underscore XFF."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/auth/login/",
        "raw_path": b"/api/auth/login/",
        "query_string": b"",
        "root_path": "",
        "client": ("172.20.0.15", 40000),
        "server": ("testserver", 80),
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(LOGIN_BODY)).encode()),
            (b"x-forwarded-for", b"10.0.0.1"),
            (b"x_forwarded_for", forged_address.encode()),
        ],
    }
    request_sent = False
    messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": LOGIN_BODY, "more_body": False}
        # Django listens for a disconnect while the view runs; never send one.
        await asyncio.Future()

    async def send(message):
        messages.append(message)

    async_to_sync(asgi_app)(scope, receive, send)
    status = next(
        (m["status"] for m in messages if m["type"] == "http.response.start"), None
    )
    assert status is not None, f"ASGI app sent no http.response.start: {messages!r}"
    return status


@pytest.mark.django_db
@one_trusted_proxy()
@patch.object(LoginThrottle, "rate", "2/min", create=True)
def test_login_throttle_ignores_an_underscore_forwarded_for(keep_test_db_connection_open):
    cache.clear()

    statuses = [_login_over_asgi(application, f"10.0.0.{90 + i}") for i in range(3)]

    assert statuses == [401, 401, 429]


@pytest.mark.django_db
@one_trusted_proxy()
@patch.object(LoginThrottle, "rate", "2/min", create=True)
def test_bare_django_asgi_app_lets_an_underscore_forwarded_for_pick_the_identity(
    keep_test_db_connection_open,
):
    """Control: without the wrapping middleware the forged spelling wins.

    Proves the test above exercises the ASGI merge rather than passing because
    the forged header never reached the throttle.
    """
    cache.clear()

    statuses = [_login_over_asgi(django_asgi_app, f"10.0.0.{90 + i}") for i in range(3)]

    assert statuses == [401, 401, 401]
