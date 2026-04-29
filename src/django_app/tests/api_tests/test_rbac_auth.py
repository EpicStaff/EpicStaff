"""
Integration tests for the Story 2 auth surface:

- First-setup idempotency + ignores body fields the endpoint no longer accepts
- Structured validation errors (AuthValidationService): aggregated + redacted
- Login valid/invalid + consistent 401 envelope
- /me via JWT / env ApiKey / user ApiKey
- Refresh rotation + blacklist
- Logout (including refresh-token ownership check)
- Login throttle (composite IP|email, 5/min)
- SSE ticket issue/consume single-use + expired + atomic
"""

from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from tables.services.rbac.sse_ticket_service import SseTicketService


# ---------------- First-setup ----------------


@pytest.mark.django_db
def test_first_setup_flow_is_idempotent(api_client):
    url = reverse("first_setup")

    r = api_client.get(url)
    assert r.status_code == 200
    assert r.json() == {"needs_setup": True}

    r = api_client.post(
        url,
        data={"email": "boss@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == status.HTTP_201_CREATED
    payload = r.json()
    assert payload["user"]["email"] == "boss@example.com"
    assert payload["user"]["is_superadmin"] is True
    assert "access" in payload and "refresh" in payload

    r = api_client.get(url)
    assert r.json() == {"needs_setup": False}

    r = api_client.post(
        url,
        data={"email": "other@example.com", "password": "AnotherPass456!"},
        format="json",
    )
    assert r.status_code == status.HTTP_409_CONFLICT


# ---------------- Login / auth envelope ----------------


@pytest.mark.django_db
def test_login_valid_credentials_returns_tokens(api_client, regular_user):
    r = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "UserStrongPass123!"},
        format="json",
    )
    assert r.status_code == 200
    body = r.json()
    assert "access" in body and "refresh" in body


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
    r = api_client.get(reverse("auth_me"))
    assert r.status_code == 401
    body = r.json()
    assert body["status_code"] == 401
    assert "code" in body
    assert "message" in body


# ---------------- /me ----------------


@pytest.mark.django_db
def test_me_via_jwt_returns_user_and_memberships(auth_client, regular_user):
    r = auth_client.get(reverse("auth_me"))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == regular_user.email
    assert isinstance(body["memberships"], list)
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["role"]["name"] == "Org Admin"


@pytest.mark.django_db
def test_me_via_env_api_key_returns_403(api_client, env_api_key):
    raw, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw)
    r = api_client.get(reverse("auth_me"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_me_via_user_api_key_returns_user(api_client, user_api_key, regular_user):
    raw, _ = user_api_key
    api_client.credentials(HTTP_X_API_KEY=raw)
    r = api_client.get(reverse("auth_me"))
    assert r.status_code == 200
    assert r.json()["email"] == regular_user.email


# ---------------- Refresh rotation / logout / blacklist ----------------


@pytest.mark.django_db
def test_refresh_rotation_invalidates_old_refresh(api_client, regular_user):
    r = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "UserStrongPass123!"},
        format="json",
    )
    old_refresh = r.json()["refresh"]

    r1 = api_client.post(
        reverse("refresh"), data={"refresh": old_refresh}, format="json"
    )
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh"]
    assert new_refresh != old_refresh

    r2 = api_client.post(
        reverse("refresh"), data={"refresh": old_refresh}, format="json"
    )
    assert r2.status_code == 401


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(api_client, regular_user, jwt_tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    r = api_client.post(
        reverse("logout"),
        data={"refresh": jwt_tokens["refresh"]},
        format="json",
    )
    assert r.status_code == status.HTTP_205_RESET_CONTENT

    api_client.credentials()
    r2 = api_client.post(
        reverse("refresh"), data={"refresh": jwt_tokens["refresh"]}, format="json"
    )
    assert r2.status_code == 401


@pytest.mark.django_db
def test_logout_rejects_malformed_refresh(api_client, jwt_tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")
    r = api_client.post(
        reverse("logout"), data={"refresh": "not-a-real-token"}, format="json"
    )
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


# ---------------- SSE ticket ----------------


@pytest.mark.django_db
def test_sse_ticket_is_single_use(auth_client, regular_user):
    cache.clear()
    r = auth_client.post(reverse("sse_ticket"))
    assert r.status_code == 200
    ticket = r.json()["ticket"]
    assert r.json()["expires_in"] == settings.SSE_TICKET_TTL_SECONDS

    service = SseTicketService()
    user = service.consume(ticket)
    assert user is not None
    assert user.pk == regular_user.pk

    # Second consume fails — GETDEL already removed the ticket atomically.
    assert service.consume(ticket) is None


@pytest.mark.django_db
def test_sse_ticket_expired_or_unknown_returns_none():
    cache.clear()
    service = SseTicketService()
    assert service.consume("no-such-ticket") is None
    assert service.consume("") is None
    assert service.consume(None) is None


@pytest.mark.django_db
def test_sse_ticket_endpoint_requires_jwt(api_client):
    r = api_client.post(reverse("sse_ticket"))
    assert r.status_code == 401


# ---------------- Logout ownership ----------------


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
    r = api_client.post(
        reverse("logout"), data={"refresh": other_refresh}, format="json"
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_or_expired_refresh"

    # The other user's refresh token must still work afterwards.
    api_client.credentials()
    r2 = api_client.post(
        reverse("refresh"), data={"refresh": other_refresh}, format="json"
    )
    assert r2.status_code == 200


# ---------------- First-setup: ignored body fields + settings-driven org ----------------


@pytest.mark.django_db
def test_first_setup_ignores_organization_name_and_display_name_in_body(api_client):
    """After the M1/M2 cleanup the endpoint silently ignores these fields;
    the org name comes from settings.DEFAULT_ORGANIZATION_NAME."""
    r = api_client.post(
        reverse("first_setup"),
        data={
            "email": "admin@example.com",
            "password": "StrongPass123!",
            "organization_name": "Rogue Corp",
            "display_name": "Rogue Name",
        },
        format="json",
    )
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["display_name"] is None
    assert body["organization"]["name"] == settings.DEFAULT_ORGANIZATION_NAME


@pytest.mark.django_db
@override_settings(DEFAULT_ORGANIZATION_NAME="Override Co")
def test_first_setup_uses_django_default_org_name_from_settings(api_client):
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "admin@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == 201
    assert r.json()["organization"]["name"] == "Override Co"


# ---------------- AuthValidationService: aggregated + redacted errors ----------------


@pytest.mark.django_db
def test_first_setup_validation_aggregates_email_and_password_errors(api_client):
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "not-an-email", "password": "12345"},
        format="json",
    )
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "invalid"
    errors = body["errors"]
    fields = {e["field"] for e in errors}
    assert "email" in fields and "password" in fields
    # Multiple password-policy reasons must be returned in one response, not one-by-one.
    password_reasons = [e["reason"] for e in errors if e["field"] == "password"]
    assert len(password_reasons) >= 2


@pytest.mark.django_db
def test_first_setup_password_similar_to_email_is_rejected(api_client):
    """Regression guard for the UserAttributeSimilarityValidator gap — this
    used to silently pass because validate_password() was called without a
    user= argument."""
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "john@acme.com", "password": "john@acme.com"},
        format="json",
    )
    assert r.status_code == 400
    reasons = [e["reason"] for e in r.json()["errors"] if e["field"] == "password"]
    assert any("similar" in reason.lower() for reason in reasons)


@pytest.mark.django_db
def test_first_setup_password_value_is_always_redacted(api_client):
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "a@b.co", "password": "password"},
        format="json",
    )
    assert r.status_code == 400
    for entry in r.json()["errors"]:
        if entry["field"] == "password":
            assert entry["value"] == "***"


@pytest.mark.django_db
def test_first_setup_missing_fields_reports_both_as_required(api_client):
    r = api_client.post(reverse("first_setup"), data={}, format="json")
    assert r.status_code == 400
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"email", "password"} <= fields


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


# ---------------- Reset-user validation ----------------


@pytest.mark.django_db
def test_reset_user_rejects_weak_password_with_structured_errors(auth_client):
    r = auth_client.post(
        reverse("reset_user"),
        data={"email": "new@example.com", "password": "12345"},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid"
    assert any(e["field"] == "password" for e in r.json()["errors"])


@pytest.mark.django_db
def test_reset_user_requires_authentication(api_client):
    r = api_client.post(
        reverse("reset_user"),
        data={"email": "new@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code in (401, 403)
