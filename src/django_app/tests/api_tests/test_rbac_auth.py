"""
Integration tests for the Story 2 auth surface:

- First-setup idempotency, optional display_name, ignored organization_name
- Structured validation errors (AuthValidationService): aggregated + redacted
- Login valid/invalid + consistent 401 envelope
- /me via JWT / env ApiKey / user ApiKey
- Refresh rotation + blacklist
- Logout (including refresh-token ownership check)
- Login throttle (composite IP|email, 5/min)
- Password-reset tokens: stored hashed, raw value only in the email
- Refresh delivered as an HttpOnly cookie, never in a response body
- SSE ticket issue/consume single-use + expired + atomic
"""

import hashlib
import json
import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.core import mail
from django.core.cache import cache
from django_redis import get_redis_connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import Organization, OrganizationUser, PasswordResetToken, Role
from rbac.models.enums import BuiltInRole
from rbac.identity.reset_user import ResetUserService
from rbac.identity.tickets import sse_ticket_service, ws_ticket_service
from rbac.identity.refresh_cookie import (
    NON_REMEMBER_REFRESH_LIFETIME,
    refresh_cookie_name,
)
from rbac.identity.passwords.token_repository import (
    PasswordResetTokenRepository,
    hash_token,
)
from rbac.identity.superadmin_bootstrap import SuperadminBootstrap
from utils.logger import logger

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"
CONSOLE_EMAIL = "django.core.mail.backends.console.EmailBackend"
OPAQUE_RESET_CODE = "invalid_or_expired_reset_token"


@pytest.fixture
def captured_log_messages():
    """Collect every loguru message emitted while the test runs, at every level."""
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", format="{message}")
    yield messages
    logger.remove(sink_id)


# ---------------- First-setup ----------------


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_first_setup_flow_is_idempotent(api_client):
    url = reverse("first_setup")

    r = api_client.get(url)
    assert r.status_code == 200
    assert r.json() == {"needs_setup": True, "setup_mode": "open"}

    r = api_client.post(
        url,
        data={"email": "boss@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == status.HTTP_201_CREATED
    payload = r.json()
    assert payload["user"]["email"] == "boss@example.com"
    assert payload["user"]["is_superadmin"] is True
    # The refresh token is delivered as an HttpOnly cookie, never in the body.
    assert "access" in payload
    assert "refresh" not in payload
    assert refresh_cookie_name() in r.cookies

    r = api_client.get(url)
    assert r.json() == {"needs_setup": False, "setup_mode": "open"}

    r = api_client.post(
        url,
        data={"email": "other@example.com", "password": "AnotherPass456!"},
        format="json",
    )
    assert r.status_code == status.HTTP_409_CONFLICT


# ---------------- Login / auth envelope ----------------


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("remember_me", "persistent"),
    [(True, True), (False, False), (None, False)],
    ids=["remember-me", "not-remembered", "remember-me-omitted"],
)
@pytest.mark.parametrize("after_refresh", [False, True], ids=["login", "after-refresh-rotation"])
def test_login_sets_an_httponly_refresh_cookie_whose_lifetime_follows_remember_me(
    api_client, regular_user, remember_me, persistent, after_refresh
):
    """Refresh lives only in an HttpOnly cookie (JavaScript cannot read it). A remembered
    session gets the full lifetime, any other a 30-minute one, and rotation keeps it."""
    data = {"email": regular_user.email, "password": "UserStrongPass123!"}
    if remember_me is not None:
        data["remember_me"] = remember_me

    r = api_client.post(reverse("login"), data=data, format="json")
    assert r.status_code == 200
    assert "access" in r.json()
    assert "refresh" not in r.json()
    if after_refresh:
        r = api_client.post(reverse("refresh"))
        assert r.status_code == 200

    cookie = r.cookies[refresh_cookie_name()]
    assert cookie["httponly"]
    lifetime = (
        settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"] if persistent else NON_REMEMBER_REFRESH_LIFETIME
    )
    assert int(cookie["max-age"]) == int(lifetime.total_seconds())
    token = RefreshToken(cookie.value)
    assert token.payload.get("remember_me") is persistent
    assert 0 < token.payload["exp"] - int(timezone.now().timestamp()) <= int(lifetime.total_seconds())


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_refresh_without_cookie_returns_401(api_client):
    r = api_client.post(reverse("refresh"))
    assert r.status_code == 401


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_refresh_with_expired_non_remember_token_returns_401_and_clears(
    api_client, regular_user
):
    """Expired non-remember refresh -> 401 + cookie cleared."""
    login = api_client.post(
        reverse("login"),
        data={
            "email": regular_user.email,
            "password": "UserStrongPass123!",
            "remember_me": False,
        },
        format="json",
    )
    assert login.status_code == 200

    # Simulate the 30-min window elapsing by re-signing exp into the past.
    current = api_client.cookies[refresh_cookie_name()].value
    token = RefreshToken(current)
    token.set_exp(
        from_time=timezone.now()
        - NON_REMEMBER_REFRESH_LIFETIME
        - timedelta(seconds=1),
        lifetime=timedelta(seconds=0),
    )
    api_client.cookies[refresh_cookie_name()] = str(token)

    r = api_client.post(reverse("refresh"))
    assert r.status_code == 401
    cleared = r.cookies[refresh_cookie_name()]
    assert cleared.value == ""
    assert int(cleared["max-age"]) == 0


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_logout_clears_refresh_cookie(api_client, regular_user, jwt_tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    api_client.cookies[refresh_cookie_name()] = jwt_tokens["refresh"]

    r = api_client.post(reverse("logout"))
    assert r.status_code == status.HTTP_205_RESET_CONTENT
    # Cookie is cleared: value emptied and Max-Age=0.
    cleared = r.cookies[refresh_cookie_name()]
    assert cleared.value == ""
    assert int(cleared["max-age"]) == 0


@pytest.mark.django_db
def test_login_invalid_credentials_returns_401(api_client, regular_user):
    r = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "wrong"},
        format="json",
    )
    assert r.status_code == 401


@pytest.mark.django_db
def test_protected_route_without_token_returns_401_project_envelope(api_client):
    # /api/profile/ is the canonical user-context protected endpoint
    # after Story 6 (replaces the removed /api/auth/me/).
    r = api_client.get("/api/profile/")
    assert r.status_code == 401
    body = r.json()
    assert body["status_code"] == 401
    assert "code" in body
    assert "message" in body


# /me/-specific tests removed in Story 6 — the endpoint was deleted in favor
# of /api/profile/. Equivalent coverage lives in
# tests/api_tests/test_rbac_user_profile.py::TestProfileGet (happy path with
# memberships, env-api-key 403). The user-api-key positive case is not
# replicated; flag a follow-up if regression coverage is desired.


# ---------------- Session-starting endpoints take JSON only ----------------
#
# A cross-site form, or a `no-cors` fetch from a plugin page, can send only these bodies
# without a CORS preflight. Taking any of them would let such a page log the browser in to an
# account of the page's choosing.


@pytest.fixture
def no_login_throttle_counts():
    cache.delete_pattern("throttle_login*")
    yield
    cache.delete_pattern("throttle_login*")


@pytest.fixture
def existing_default_org(db):
    """The default organization first setup joins, so the setup creates none."""
    return Organization.objects.create(name="Organization", is_default=True)


def _form_encoded(client, url, body):
    return client.post(url, urlencode(body), content_type="application/x-www-form-urlencoded")


def _multipart(client, url, body):
    return client.post(url, body, format="multipart")


def _text_plain(client, url, body):
    return client.post(url, json.dumps(body), content_type="text/plain")


def _empty_text_plain(client, url, body):
    return client.post(url, "", content_type="text/plain")


def _no_content_type(client, url, body):
    return client.generic("POST", url, json.dumps(body).encode(), content_type="")


NON_JSON_BODIES = [_form_encoded, _multipart, _text_plain, _empty_text_plain, _no_content_type]
NON_JSON_IDS = ["form-encoded", "multipart", "text-plain", "empty-text-plain", "no-content-type"]


@pytest.mark.django_db
@pytest.mark.usefixtures("refresh_cookie_secure", "no_login_throttle_counts")
@pytest.mark.parametrize("send", NON_JSON_BODIES, ids=NON_JSON_IDS)
def test_login_refuses_a_body_that_is_not_json_and_sets_no_cookie(api_client, regular_user, send):
    # The right password, so only the media type can refuse it.
    response = send(api_client, reverse("login"), {"email": regular_user.email, "password": "UserStrongPass123!"})

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert response.json()["code"] == "unsupported_media_type"
    assert not response.cookies
    assert "access" not in response.json()


@pytest.mark.django_db
@pytest.mark.usefixtures("refresh_cookie_secure", "existing_default_org")
@pytest.mark.parametrize("send", NON_JSON_BODIES, ids=NON_JSON_IDS)
def test_first_setup_refuses_a_body_that_is_not_json_and_creates_nobody(api_client, send):
    response = send(api_client, reverse("first_setup"), {"email": "first@example.com", "password": "StrongPass123!"})

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert response.json()["code"] == "unsupported_media_type"
    assert not response.cookies
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("refresh_cookie_secure", "no_login_throttle_counts")
@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8", "Application/JSON"])
def test_login_takes_json_with_parameters_and_in_any_case(api_client, regular_user, content_type):
    body = json.dumps({"email": regular_user.email, "password": "UserStrongPass123!"})

    response = api_client.post(reverse("login"), body, content_type=content_type)

    assert response.status_code == status.HTTP_200_OK
    assert refresh_cookie_name() in response.cookies


@pytest.mark.django_db
@pytest.mark.usefixtures("refresh_cookie_secure", "existing_default_org")
def test_first_setup_takes_json(api_client):
    response = api_client.post(
        reverse("first_setup"), data={"email": "first@example.com", "password": "StrongPass123!"}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert refresh_cookie_name() in response.cookies


# ---------------- Refresh rotation / logout / blacklist ----------------


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_refresh_rotation_invalidates_old_refresh(api_client, regular_user):
    r = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "UserStrongPass123!"},
        format="json",
    )
    old_refresh = r.cookies[refresh_cookie_name()].value

    # The test client carries the cookie forward, so no body is needed.
    r1 = api_client.post(reverse("refresh"))
    assert r1.status_code == 200
    new_refresh = r1.cookies[refresh_cookie_name()].value
    assert new_refresh != old_refresh

    # Put the rotated-away token back to prove replaying it is rejected.
    api_client.cookies[refresh_cookie_name()] = old_refresh
    r2 = api_client.post(reverse("refresh"))
    assert r2.status_code == 401


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_logout_blacklists_refresh_token(api_client, regular_user, jwt_tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    # Logout reads the refresh from the cookie; a body would be ignored, which
    # would make this test pass without blacklisting anything.
    api_client.cookies[refresh_cookie_name()] = jwt_tokens["refresh"]

    r = api_client.post(reverse("logout"))
    assert r.status_code == status.HTTP_205_RESET_CONTENT

    api_client.credentials()
    api_client.cookies[refresh_cookie_name()] = jwt_tokens["refresh"]
    r2 = api_client.post(reverse("refresh"))
    assert r2.status_code == 401


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_logout_rejects_malformed_refresh(api_client, jwt_tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    api_client.cookies[refresh_cookie_name()] = "not-a-real-token"
    r = api_client.post(reverse("logout"))
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_or_expired_refresh"


# ---------------- Throttling ----------------


@pytest.mark.django_db
def test_login_throttle_blocks_6th_attempt_with_retry_after(api_client, regular_user):
    cache.clear()
    url = reverse("login")
    for _ in range(5):
        api_client.post(
            url,
            data={"email": regular_user.email, "password": "wrong"},
            format="json",
        )
    r = api_client.post(
        url,
        data={"email": regular_user.email, "password": "wrong"},
        format="json",
    )
    assert r.status_code == 429
    assert "Retry-After" in r.headers or "retry-after" in {k.lower() for k in r.headers}


@pytest.mark.django_db
def test_login_throttle_is_per_email(api_client, regular_user):
    cache.clear()
    url = reverse("login")
    for _ in range(5):
        api_client.post(
            url,
            data={"email": regular_user.email, "password": "wrong"},
            format="json",
        )
    r = api_client.post(
        url,
        data={"email": "other@example.com", "password": "wrong"},
        format="json",
    )
    # Different email -> different bucket -> not throttled (would be 401 instead)
    assert r.status_code != 429


# The per-IP throttles on token-refresh and password-reset-confirm live in
# tests/api_tests/test_auth_throttles.py.


# ---------------- SSE ticket ----------------


@pytest.mark.django_db
def test_sse_ticket_is_single_use(auth_client, regular_user):
    cache.clear()
    r = auth_client.post(reverse("sse_ticket"))
    assert r.status_code == 200
    ticket = r.json()["ticket"]
    assert r.json()["expires_in"] == settings.SSE_TICKET_TTL

    user = sse_ticket_service.consume(ticket)
    assert user is not None
    assert user.pk == regular_user.pk

    # Second consume fails — GETDEL already removed the ticket atomically.
    assert sse_ticket_service.consume(ticket) is None


@pytest.mark.django_db
def test_sse_ticket_endpoint_requires_jwt(api_client):
    r = api_client.post(reverse("sse_ticket"))
    assert r.status_code == 401


# ---------------- Ticket at rest ----------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "service, prefix",
    [
        (sse_ticket_service, "rbac:sse_ticket:"),
        (ws_ticket_service, "rbac:ws_ticket:"),
    ],
    ids=["sse", "ws"],
)
def test_redis_never_holds_the_raw_ticket(regular_user, service, prefix: str):
    """Read access to Redis must not yield a replayable ticket.

    The key is the SHA-256 digest of the ticket, so `SCAN MATCH "<prefix>*"`
    returns digests that cannot be inverted into a usable ticket.
    """
    cache.clear()
    ticket, _ = service.issue(regular_user)

    keys = [key.decode() for key in get_redis_connection("default").keys(f"{prefix}*")]
    expected = f"{prefix}{hashlib.sha256(ticket.encode('utf-8')).hexdigest()}"
    assert keys == [expected]
    assert ticket not in keys[0]

    # The raw ticket still resolves; only its storage form changed.
    assert service.consume(ticket).pk == regular_user.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "service", [sse_ticket_service, ws_ticket_service], ids=["sse", "ws"]
)
def test_consume_rejects_unknown_and_non_string_tickets(service):
    cache.clear()
    assert service.consume("no-such-ticket") is None
    assert service.consume(None) is None
    assert service.consume(12345) is None
    assert service.consume("") is None


# ---------------- Logout ownership ----------------


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_logout_rejects_refresh_owned_by_another_user(
    api_client, regular_user, jwt_tokens
):
    """A leaked refresh token belonging to user B must not be blacklistable
    by user A, even when A presents a valid access token of their own."""
    other = get_user_model().objects.create_user(
        email="other@example.com", password="OtherPass123!"
    )
    other_refresh = str(RefreshToken.for_user(other))

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    api_client.cookies[refresh_cookie_name()] = other_refresh
    r = api_client.post(reverse("logout"))
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_or_expired_refresh"

    # The other user's refresh token must still work afterwards.
    api_client.credentials()
    api_client.cookies[refresh_cookie_name()] = other_refresh
    r2 = api_client.post(reverse("refresh"))
    assert r2.status_code == 200


# ---------------- First-setup: body display_name + settings-driven org ----------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("extra_body", "default_org_name", "expected_display_name"),
    [
        # organization_name in the body is ignored: the org name comes from settings.
        ({"email": "admin@example.com", "organization_name": "Rogue Corp"}, None, "Admin"),
        ({"email": "admin@example.com"}, "Override Co", "Admin"),
        ({"email": "admin@example.com", "display_name": "  Jane Doe  "}, None, "Jane Doe"),
        ({"email": "john.smith@example.com", "display_name": None}, None, "John Smith"),
        ({"email": "john.smith@example.com"}, None, "John Smith"),
        ({"email": "admin@example.com", "display_name": "x" * 255}, None, "x" * 255),
    ],
    ids=["org-name-in-body-ignored", "org-name-from-settings", "display-name-trimmed",
         "null-display-name-derived", "missing-display-name-derived", "display-name-max-length"],
)
def test_first_setup_creates_the_superadmin_and_default_org(
    api_client, settings, extra_body, default_org_name, expected_display_name
):
    if default_org_name is not None:
        settings.DEFAULT_ORGANIZATION_NAME = default_org_name

    r = api_client.post(
        reverse("first_setup"), data={"password": "StrongPass123!", **extra_body}, format="json"
    )

    assert r.status_code == 201, r.content
    assert r.json()["organization"]["name"] == settings.DEFAULT_ORGANIZATION_NAME
    assert r.json()["user"]["display_name"] == expected_display_name
    assert get_user_model().objects.get(email=extra_body["email"]).display_name == expected_display_name


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("display_name", "reason"),
    [
        ("   ", "Must not be blank. Omit it or use null to derive it from the email."),
        ("x" * 256, "Must be 255 characters or fewer."),
        (123, "Must be a string or null."),
    ],
    ids=["blank", "too-long", "not-a-string"],
)
def test_first_setup_rejects_invalid_display_name(api_client, display_name, reason):
    r = api_client.post(
        reverse("first_setup"),
        data={
            "email": "admin@example.com",
            "password": "StrongPass123!",
            "display_name": display_name,
        },
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["errors"] == [
        {"field": "display_name", "value": display_name, "reason": reason}
    ]
    assert not get_user_model().objects.exists()


# ---------------- AuthValidationService: aggregated + redacted errors ----------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "fields", "password_reason"),
    [
        # Every password-policy reason comes back at once, not one per attempt.
        ({"email": "not-an-email", "password": "12345"}, {"email", "password"}, None),
        ({"email": "not-an-email", "password": "StrongPass123!", "display_name": "   "}, {"email", "display_name"}, None),
        # UserAttributeSimilarityValidator used to pass silently (validate_password had no user=).
        ({"email": "john@acme.com", "password": "john@acme.com"}, {"password"}, "similar"),
        ({"email": "a@b.co", "password": "password"}, {"password"}, None),
        ({}, {"email", "password"}, None),
    ],
    ids=["email-and-weak-password", "email-and-display-name", "password-like-email", "common-password", "nothing"],
)
def test_first_setup_reports_every_invalid_field_at_once_without_echoing_the_password(
    api_client, body, fields, password_reason
):
    r = api_client.post(reverse("first_setup"), data=body, format="json")

    assert r.status_code == 400
    assert r.json()["code"] == "invalid"
    errors = r.json()["errors"]
    assert fields <= {error["field"] for error in errors}
    password_errors = [error for error in errors if error["field"] == "password"]
    assert all(error["value"] == "***" for error in password_errors)
    if body.get("password") == "12345":
        assert len(password_errors) >= 2
    if password_reason:
        assert any(password_reason in error["reason"].lower() for error in password_errors)
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_login_missing_fields_returns_structured_errors(api_client):
    r = api_client.post(reverse("login"), data={}, format="json")
    assert r.status_code == 400
    body = r.json()
    fields = {e["field"] for e in body["errors"]}
    assert {"email", "password"} <= fields


@pytest.mark.django_db
def test_login_wrong_credentials_has_no_errors_array(api_client, regular_user):
    """User-enumeration guard: wrong creds must not disclose which field failed."""
    r = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "wrong"},
        format="json",
    )
    assert r.status_code == 401
    assert "errors" not in r.json()


# ---------------- Password recovery: request ----------------


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_known_user_creates_token_and_sends_email(
    api_client, regular_user
):
    cache.clear()
    mail.outbox = []
    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["smtp_configured"] is True
    assert body["detail"]
    tokens = PasswordResetToken.objects.filter(user=regular_user)
    assert tokens.count() == 1
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert regular_user.email in msg.to
    # The raw token exists only in this email — the row stores its hash. Pull
    # it back out of the link and prove the database holds a verifier, not the
    # secret itself.
    match = re.search(r"token=([A-Za-z0-9_\-]+)", msg.body)
    assert match is not None
    assert hash_token(match.group(1)) == tokens.first().token_hash


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_password_reset_request_smtp_off_issues_no_token_and_sends_nothing(
    api_client, regular_user
):
    """Without SMTP the request is ignored, and a known email is indistinguishable
    from an unknown one."""
    cache.clear()
    mail.outbox = []
    url = reverse("password_reset_request")

    known = api_client.post(url, data={"email": regular_user.email}, format="json")
    unknown = api_client.post(
        url, data={"email": "nobody@example.com"}, format="json"
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.json()["smtp_configured"] is False
    assert known.json()["detail"] == (
        "Password reset by email isn't available on this server. "
        "Ask your administrator to reset your password."
    )
    assert PasswordResetToken.objects.count() == 0
    assert mail.outbox == []


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_password_reset_request_smtp_off_keeps_a_pending_grant(
    api_client, regular_user
):
    """An anonymous caller must not be able to cancel a grant issued earlier."""
    cache.clear()
    pending, _raw_token = PasswordResetTokenRepository().create_for_user(regular_user)

    api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )

    assert PasswordResetToken.objects.filter(pk=pending.pk).exists()


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=CONSOLE_EMAIL, EMAIL_HOST="")
def test_password_reset_request_smtp_off_writes_no_reset_link_anywhere(
    api_client, regular_user, capsys, captured_log_messages
):
    """With the shipped no-SMTP default (console backend) nothing that carries a
    reset link reaches stdout, stderr or the application log.

    The console backend writes to `sys.stdout`, which `capsys` captures, and
    loguru output is collected by a sink — so a link sent by either route would
    show up below.
    """
    cache.clear()

    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )

    assert r.status_code == 200
    assert PasswordResetToken.objects.count() == 0
    stdout, stderr = capsys.readouterr()
    written = "\n".join([stdout, stderr, *captured_log_messages])
    assert "token=" not in written
    assert settings.FRONTEND_PASSWORD_RESET_PATH not in written
    assert regular_user.email not in written


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_password_reset_request_smtp_off_logs_one_operator_hint_per_window(
    api_client, regular_user, captured_log_messages
):
    """The endpoint is anonymous and rotating emails beats its throttle, so the
    operator hint must not grow with the number of requests."""
    cache.clear()
    url = reverse("password_reset_request")

    for index in range(3):
        api_client.post(url, data={"email": f"probe{index}@example.com"}, format="json")

    hints = [
        message
        for message in captured_log_messages
        if "password_reset_request_ignored_smtp_not_configured" in message
    ]
    assert len(hints) == 1
    assert "manage.py reset_password" in hints[0]
    assert "probe" not in hints[0]


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_unknown_email_is_uniform(api_client, regular_user):
    """No-enumeration guard with SMTP on: an unknown email gets the same body as a
    known one, but no token row and no email."""
    cache.clear()
    url = reverse("password_reset_request")
    known = api_client.post(url, data={"email": regular_user.email}, format="json")
    PasswordResetToken.objects.all().delete()
    mail.outbox = []

    unknown = api_client.post(
        url, data={"email": "nobody@example.com"}, format="json"
    )

    assert known.status_code == unknown.status_code == 200
    assert unknown.json() == known.json()
    assert unknown.json()["smtp_configured"] is True
    assert PasswordResetToken.objects.count() == 0
    assert mail.outbox == []


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_resolves_user_case_insensitively(
    api_client, regular_user
):
    cache.clear()
    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email.upper()},
        format="json",
    )
    assert r.status_code == 200
    assert PasswordResetToken.objects.filter(user=regular_user).count() == 1


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_invalidates_prior_tokens_for_same_user(
    api_client, regular_user
):
    cache.clear()
    api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )
    api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )
    # Requesting again deletes the earlier grant rather than flagging it, so
    # exactly one row survives and it is the newest.
    rows = PasswordResetToken.objects.filter(user=regular_user)
    assert rows.count() == 1


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_email_failure_does_not_break_response(
    api_client, regular_user
):
    """SMTP failure must not change the HTTP contract — still 200, token still created.

    Patches `django.core.mail.send_mail` so the sender's own try/except
    runs and swallows the error (that fail-silent guarantee is the thing
    under test)."""
    cache.clear()
    with patch(
        "rbac.identity.passwords.email_sender.send_mail",
        side_effect=RuntimeError("smtp blew up"),
    ):
        r = api_client.post(
            reverse("password_reset_request"),
            data={"email": regular_user.email},
            format="json",
        )
    assert r.status_code == 200
    assert PasswordResetToken.objects.filter(user=regular_user).count() == 1


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_throttle_blocks_after_limit(api_client, regular_user):
    cache.clear()
    url = reverse("password_reset_request")
    for _ in range(5):
        api_client.post(url, data={"email": regular_user.email}, format="json")
    r = api_client.post(url, data={"email": regular_user.email}, format="json")
    assert r.status_code == 429


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="smtp.example.com")
def test_password_reset_request_throttle_is_per_email(api_client, regular_user):
    cache.clear()
    url = reverse("password_reset_request")
    for _ in range(5):
        api_client.post(url, data={"email": regular_user.email}, format="json")
    r = api_client.post(url, data={"email": "someone-else@example.com"}, format="json")
    assert r.status_code != 429


# ---------------- Password recovery: confirm ----------------


def _issue_token(user) -> tuple[PasswordResetToken, str]:
    """Create a reset grant and return `(row, raw_token)`.

    Goes through the repository rather than `objects.create` so the test
    exercises the real generation path — only the hash is stored, and the raw
    value is available exactly once, here.
    """
    return PasswordResetTokenRepository().create_for_user(user)


@pytest.mark.django_db
def test_password_reset_confirm_happy_path(api_client, regular_user, jwt_tokens):
    token, raw_token = _issue_token(regular_user)
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert r.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.check_password("BrandNewPass123!")
    assert not regular_user.check_password("UserStrongPass123!")
    # Consuming deletes the grant, so single-use holds because the row is gone.
    assert not PasswordResetToken.objects.filter(pk=token.pk).exists()
    # Outstanding refresh token from `jwt_tokens` fixture must now be blacklisted.
    assert OutstandingToken.objects.filter(user=regular_user).exists()
    assert (
        BlacklistedToken.objects.filter(token__user=regular_user).count()
        == OutstandingToken.objects.filter(user=regular_user).count()
    )


@pytest.mark.django_db
def test_password_reset_confirm_revokes_the_users_api_keys(
    api_client, regular_user, superadmin_user, issue_api_key
):
    """A key minted during an account takeover must not survive the reset."""
    raw_key, user_key = issue_api_key(user=regular_user)
    _, other_users_key = issue_api_key(user=superadmin_user)
    _, system_key = issue_api_key(user=None)
    _token, raw_token = _issue_token(regular_user)

    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": "BrandNewPass123!"},
        format="json",
    )

    assert r.status_code == 200
    user_key.refresh_from_db()
    other_users_key.refresh_from_db()
    system_key.refresh_from_db()
    assert user_key.revoked_at is not None
    assert other_users_key.revoked_at is None
    assert system_key.revoked_at is None
    api_client.credentials(HTTP_X_API_KEY=raw_key)
    assert api_client.get("/api/profile/").status_code == 401


def _expire(token):
    PasswordResetToken.objects.filter(pk=token.pk).update(
        created_at=timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TOKEN_TTL + 60)
    )


def _spend(api_client, raw_token):
    assert api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": "BrandNewPass123!"},
        format="json",
    ).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "spoil",
    [
        lambda api_client, token, raw: "00000000-0000-0000-0000-000000000000",
        # The token is opaque: a malformed value is just another lookup miss.
        lambda api_client, token, raw: "not-a-real-token",
        lambda api_client, token, raw: _expire(token) or raw,
        lambda api_client, token, raw: _spend(api_client, raw) or raw,
    ],
    ids=["unknown", "garbage", "expired", "already-used"],
)
def test_password_reset_confirm_with_an_unusable_token_gets_one_opaque_answer(
    api_client, regular_user, spoil
):
    token, raw_token = _issue_token(regular_user)
    presented = spoil(api_client, token, raw_token)

    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": presented, "new_password": "AnotherPass456!"},
        format="json",
    )

    assert r.status_code == 400
    assert r.json()["code"] == OPAQUE_RESET_CODE
    regular_user.refresh_from_db()
    assert not regular_user.check_password("AnotherPass456!")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"new_password": "12345"}, {"new_password"}),
        ({"token": "", "new_password": "BrandNewPass123!"}, {"token"}),
        ({}, {"token", "new_password"}),
    ],
    ids=["weak-password", "blank-token", "nothing"],
)
def test_password_reset_confirm_field_errors_keep_the_grant_and_redact_the_password(
    api_client, regular_user, body, fields
):
    token, raw_token = _issue_token(regular_user)
    if "new_password" in body and "token" not in body:
        body = {"token": raw_token, **body}

    r = api_client.post(reverse("password_reset_confirm"), data=body, format="json")

    assert r.status_code == 400
    errors = r.json()["errors"]
    assert fields <= {error["field"] for error in errors}
    assert all(error["value"] == "***" for error in errors if error["field"] == "new_password")
    # A rejected request must leave the grant spendable and the password unchanged.
    assert PasswordResetToken.objects.filter(pk=token.pk).exists()
    regular_user.refresh_from_db()
    assert regular_user.check_password("UserStrongPass123!")


# Self-service password-change tests removed in Story 6 — the single-step
# /api/auth/password-change/ endpoint was deleted in favor of the two-step
# /api/profile/password-change/{request,confirm}/ flow. Equivalent test
# coverage now lives in tests/api_tests/test_rbac_user_profile.py under
# TestPasswordChangeRequest / TestPasswordChangeConfirm.


# ---------------- Password recovery: admin reset ----------------


def _superadmin(api_client, superadmin_user):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    return api_client


@pytest.mark.django_db
def test_admin_password_reset_sets_the_password_and_ends_the_users_sessions_and_keys(
    api_client, superadmin_user, regular_user, issue_api_key
):
    _, user_key = issue_api_key(user=regular_user)
    _, other_users_key = issue_api_key(user=superadmin_user)
    _, system_key = issue_api_key(user=None)
    RefreshToken.for_user(regular_user)

    r = _superadmin(api_client, superadmin_user).post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": "AdminSet123!"},
        format="json",
    )

    assert r.status_code == 204
    regular_user.refresh_from_db()
    assert regular_user.check_password("AdminSet123!")
    assert BlacklistedToken.objects.filter(token__user=regular_user).exists()
    for key in (user_key, other_users_key, system_key):
        key.refresh_from_db()
    assert user_key.revoked_at is not None
    assert (other_users_key.revoked_at, system_key.revoked_at) == (None, None)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "body", "status_code", "check"),
    [
        ("anonymous", {"new_password": "AdminSet123!"}, 401, None),
        # Rejected by IsSuperadmin with the standard envelope.
        ("org-admin", {"new_password": "AdminSet123!"}, 403, ("code", "permission_denied")),
        ("superadmin", {"user_id": 999_999, "new_password": "AdminSet123!"}, 404, ("code", "user_not_found")),
        ("superadmin", {"new_password": "12345"}, 400, ("field", "new_password")),
        ("superadmin", {"user_id": "not-an-int", "new_password": "AdminSet123!"}, 400, ("field", "user_id")),
        ("superadmin", {"new_password": "abcd 1234"}, 400, ("field", "new_password")),
    ],
    ids=["anonymous", "not-superadmin", "unknown-user", "weak-password", "bad-user-id", "password-outside-alphabet"],
)
def test_admin_password_reset_refusals_leave_the_password_alone(
    api_client, auth_client, superadmin_user, regular_user, caller, body, status_code, check
):
    # auth_client is api_client with credentials set, so anonymous needs a client of its own.
    client = {
        "anonymous": APIClient(),
        "org-admin": auth_client,
    }.get(caller) or _superadmin(api_client, superadmin_user)

    r = client.post(
        reverse("admin_password_reset"), data={"user_id": regular_user.id, **body}, format="json"
    )

    assert r.status_code == status_code
    if check and check[0] == "code":
        assert r.json()["code"] == check[1]
    elif check:
        assert check[1] in {error["field"] for error in r.json()["errors"]}
    regular_user.refresh_from_db()
    assert regular_user.check_password("UserStrongPass123!")


# ------------------------------------------------------------------
# PrintableAsciiPasswordValidator — unit tests
# ------------------------------------------------------------------
from django.core.exceptions import ValidationError as _DjangoValidationError

from rbac.identity.passwords.validators import (
    PrintableAsciiPasswordValidator,
)


class TestPrintableAsciiPasswordValidator:
    """Pure unit tests for the alphabet validator. No DB, no client."""

    def setup_method(self):
        self.validator = PrintableAsciiPasswordValidator()

    @pytest.mark.parametrize(
        "password",
        [
            "Abcd1234",
            "P@ssw0rd!",
            "hunter2!@#$%^&*()",
            "ALLCAPS123",
            "all_lower_99",
            "~!@#$%^&*()_+`-={}[]|\\:;\"'<>,.?/",
        ],
    )
    def test_accepts_printable_ascii(self, password):
        self.validator.validate(password)

    @pytest.mark.parametrize(
        "password",
        [
            "        ",
            "abcd 1234",
            " abcd1234",
            "abcd1234 ",
            "abcd\t1234",
            "abcd\n1234",
            "abcd\r1234",
            "Pässwörd1",
            "♫abcd1234",
            "emoji😀1234",
            "abc​1234",  # zero-width space
            "abc\x7f1234",
            "abc\x01def",
            "",
        ],
    )
    def test_rejects_disallowed(self, password):
        with pytest.raises(_DjangoValidationError) as exc_info:
            self.validator.validate(password)
        assert exc_info.value.code == "password_invalid_characters"

    def test_help_text_mentions_allowed_set(self):
        text = self.validator.get_help_text()
        assert "Latin letters" in text
        assert "digits" in text
        assert "ASCII" in text


# The alphabet itself is pinned by the validator table above; each endpoint only needs
# to prove the validator is wired in (admin reset: see the refusal table).


@pytest.mark.django_db
def test_first_setup_rejects_a_password_outside_the_alphabet(api_client):
    r = api_client.post(
        reverse("first_setup"), data={"email": "admin@acme.com", "password": "Pässwörd1"}, format="json"
    )

    assert r.status_code == 400
    assert any(
        "only Latin letters, digits, and standard ASCII symbols" in error["reason"]
        for error in r.json()["errors"]
        if error["field"] == "password"
    )


@pytest.mark.django_db
def test_password_reset_confirm_rejects_a_password_outside_the_alphabet(api_client, regular_user):
    _token, raw_token = _issue_token(regular_user)

    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": "Pässwörd1"},
        format="json",
    )

    assert r.status_code == 400
    assert any(
        "only Latin letters, digits, and standard ASCII symbols" in error["reason"]
        for error in r.json()["errors"]
        if error["field"] == "new_password"
    )


# ---------------- Email validation ----------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("email", "reason"),
    [
        ("not-an-email", None),
        (None, None),
        ("user @example.com", "must not contain whitespace"),
        (" user@example.com", "must not contain whitespace"),
        ("user@example.com\n", "must not contain whitespace"),
        ("user@\texample.com", "must not contain whitespace"),
        # Non-strings must be a 400, not a 500 from the ip|email throttle key.
        (123, "must be a string"),
        (["x@y.com"], "must be a string"),
        ({"a": 1}, "must be a string"),
        (True, "must be a string"),
    ],
)
def test_password_reset_request_with_an_invalid_email_is_a_field_error(api_client, email, reason):
    cache.clear()
    body = {} if email is None else {"email": email}

    r = api_client.post(reverse("password_reset_request"), data=body, format="json")

    assert r.status_code == 400, r.content
    email_errors = [error for error in r.json()["errors"] if error["field"] == "email"]
    assert email_errors
    if reason:
        assert any(reason in error["reason"].lower() for error in email_errors)


@pytest.mark.django_db
def test_first_setup_rejects_an_email_with_whitespace(api_client):
    r = api_client.post(
        reverse("first_setup"), data={"email": "user @example.com", "password": "P@ssw0rd!9"}, format="json"
    )

    assert r.status_code == 400
    assert any(
        "must not contain whitespace" in error["reason"].lower()
        for error in r.json()["errors"]
        if error["field"] == "email"
    )


# ---------------- Default-org: single-default constraint ----------------


@pytest.mark.django_db
def test_only_one_org_can_be_default():
    Organization.objects.create(name="Alpha", is_default=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Organization.objects.create(name="Beta", is_default=True)


@pytest.mark.django_db
def test_many_orgs_can_be_non_default():
    Organization.objects.create(name="Alpha", is_default=False)
    Organization.objects.create(name="Beta", is_default=False)
    assert Organization.objects.filter(is_default=False).count() == 2


# ---------------- Default-org: flag-first bootstrap resolution ----------------


@pytest.mark.django_db
def test_bootstrap_creates_flagged_default_org_on_empty_db():
    # Superadmin role is seeded by conftest's session fixture.
    assert Role.objects.filter(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    ).exists()
    result = SuperadminBootstrap().provision(
        email="a@example.com", password="StrongPass123!"
    )
    assert result.organization.is_default is True
    assert result.default_org_created is True
    assert Organization.objects.filter(is_default=True).count() == 1


@pytest.mark.django_db
def test_bootstrap_reuses_flagged_org_regardless_of_name():
    # The flagged org is named differently from DEFAULT_ORGANIZATION_NAME; a
    # name-based resolver would create a second "Organization" row.
    flagged = Organization.objects.create(name="Renamed Co", is_default=True)
    result = SuperadminBootstrap().provision(
        email="a@example.com", password="StrongPass123!"
    )
    assert result.organization.id == flagged.id
    assert result.default_org_created is False
    assert Organization.objects.count() == 1  # no duplicate "Organization"


@pytest.mark.django_db
@override_settings(DEFAULT_ORGANIZATION_NAME="Acme")
def test_bootstrap_self_heals_unflagged_name_matched_org():
    # Org exists by configured name but predates the flag.
    legacy = Organization.objects.create(name="Acme", is_default=False)
    result = SuperadminBootstrap().provision(
        email="a@example.com", password="StrongPass123!"
    )
    legacy.refresh_from_db()
    assert result.organization.id == legacy.id
    assert result.default_org_created is False
    assert legacy.is_default is True


@pytest.mark.django_db
def test_reset_user_after_rename_reuses_org_no_duplicate():
    SuperadminBootstrap().provision(
        email="first@example.com", password="StrongPass123!"
    )
    org = Organization.objects.get(is_default=True)
    org.name = "Renamed Co"
    org.save(update_fields=["name"])

    ResetUserService().reset(email="second@example.com", password="StrongPass123!")

    assert Organization.objects.count() == 1
    survivor = Organization.objects.get(is_default=True)
    assert survivor.name == "Renamed Co"
    assert OrganizationUser.objects.filter(org=survivor).count() == 1
