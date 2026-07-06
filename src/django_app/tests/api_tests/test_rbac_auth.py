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

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import PasswordResetToken
from tables.services.rbac.ticket_service import sse_ticket_service

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"
OPAQUE_RESET_CODE = "invalid_or_expired_reset_token"


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

    user = sse_ticket_service.consume(ticket)
    assert user is not None
    assert user.pk == regular_user.pk

    # Second consume fails — GETDEL already removed the ticket atomically.
    assert sse_ticket_service.consume(ticket) is None


@pytest.mark.django_db
def test_sse_ticket_expired_or_unknown_returns_none():
    cache.clear()
    assert sse_ticket_service.consume("no-such-ticket") is None
    assert sse_ticket_service.consume("") is None
    assert sse_ticket_service.consume(None) is None


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
def test_reset_user_rejects_weak_password_with_structured_errors(superadmin_client):
    r = superadmin_client.post(
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


@pytest.mark.django_db
def test_reset_user_creates_default_org_membership(superadmin_client):
    """Bug 1 regression: after POST /api/auth/reset-user/, the new superadmin
    must have an OrganizationUser row in the DEFAULT_ORGANIZATION_NAME-named
    org with role 'Superadmin'.
    """
    from django.conf import settings
    from tables.models.rbac_models import Organization, OrganizationUser

    r = superadmin_client.post(
        reverse("reset_user"),
        data={"email": "new-admin@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == 201, r.content

    new_user = get_user_model().objects.get(email="new-admin@example.com")
    org = Organization.objects.get(name__iexact=settings.DEFAULT_ORGANIZATION_NAME)
    membership = OrganizationUser.objects.get(user=new_user, org=org)
    assert membership.role.name == "Superadmin"
    assert membership.role.is_built_in is True


@pytest.mark.django_db
def test_reset_user_creates_default_org_when_missing(superadmin_client):
    """If the default org doesn't exist at reset time (e.g. it was deleted
    out of band), reset-user creates it via SuperadminBootstrap and the
    new superadmin's membership lands in the freshly-created org.
    """
    from django.conf import settings
    from tables.models.rbac_models import Organization, OrganizationUser

    Organization.objects.filter(
        name__iexact=settings.DEFAULT_ORGANIZATION_NAME
    ).delete()

    r = superadmin_client.post(
        reverse("reset_user"),
        data={"email": "new-admin2@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == 201, r.content

    new_user = get_user_model().objects.get(email="new-admin2@example.com")
    org = Organization.objects.get(name__iexact=settings.DEFAULT_ORGANIZATION_NAME)
    assert OrganizationUser.objects.filter(user=new_user, org=org).exists()


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
    tokens = PasswordResetToken.objects.filter(user=regular_user, is_used=False)
    assert tokens.count() == 1
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert regular_user.email in msg.to
    assert str(tokens.first().token) in msg.body


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL, EMAIL_HOST="")
def test_password_reset_request_smtp_off_still_creates_token(api_client, regular_user):
    cache.clear()
    mail.outbox = []
    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": regular_user.email},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["smtp_configured"] is False
    assert PasswordResetToken.objects.filter(user=regular_user).count() == 1


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL)
def test_password_reset_request_unknown_email_is_uniform(api_client, regular_user):
    """No-enumeration guard: identical body, no token row, no email."""
    cache.clear()
    mail.outbox = []
    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": "nobody@example.com"},
        format="json",
    )
    assert r.status_code == 200
    assert "detail" in r.json() and "smtp_configured" in r.json()
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
def test_password_reset_request_malformed_email_returns_structured_400(api_client):
    cache.clear()
    r = api_client.post(
        reverse("password_reset_request"),
        data={"email": "not-an-email"},
        format="json",
    )
    assert r.status_code == 400
    fields = {e["field"] for e in r.json()["errors"]}
    assert "email" in fields


@pytest.mark.django_db
def test_password_reset_request_missing_email_returns_400(api_client):
    cache.clear()
    r = api_client.post(reverse("password_reset_request"), data={}, format="json")
    assert r.status_code == 400
    assert any(e["field"] == "email" for e in r.json()["errors"])


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
    rows = PasswordResetToken.objects.filter(user=regular_user).order_by("created_at")
    assert rows.count() == 2
    assert rows.first().is_used is True
    assert rows.last().is_used is False


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
        "tables.services.rbac.utils.password_reset_email_sender.send_mail",
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
def test_password_reset_request_throttle_blocks_after_limit(api_client, regular_user):
    cache.clear()
    url = reverse("password_reset_request")
    for _ in range(5):
        api_client.post(url, data={"email": regular_user.email}, format="json")
    r = api_client.post(url, data={"email": regular_user.email}, format="json")
    assert r.status_code == 429


@pytest.mark.django_db
def test_password_reset_request_throttle_is_per_email(api_client, regular_user):
    cache.clear()
    url = reverse("password_reset_request")
    for _ in range(5):
        api_client.post(url, data={"email": regular_user.email}, format="json")
    r = api_client.post(url, data={"email": "someone-else@example.com"}, format="json")
    assert r.status_code != 429


# ---------------- Password recovery: confirm ----------------


def _issue_token(user) -> PasswordResetToken:
    return PasswordResetToken.objects.create(user=user)


@pytest.mark.django_db
def test_password_reset_confirm_happy_path(api_client, regular_user, jwt_tokens):
    token = _issue_token(regular_user)
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert r.status_code == 200
    regular_user.refresh_from_db()
    assert regular_user.check_password("BrandNewPass123!")
    assert not regular_user.check_password("UserStrongPass123!")
    token.refresh_from_db()
    assert token.is_used is True
    # Outstanding refresh token from `jwt_tokens` fixture must now be blacklisted.
    assert OutstandingToken.objects.filter(user=regular_user).exists()
    assert (
        BlacklistedToken.objects.filter(token__user=regular_user).count()
        == OutstandingToken.objects.filter(user=regular_user).count()
    )


@pytest.mark.django_db
def test_password_reset_confirm_unknown_token_returns_opaque_400(api_client):
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={
            "token": "00000000-0000-0000-0000-000000000000",
            "new_password": "BrandNewPass123!",
        },
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == OPAQUE_RESET_CODE


@pytest.mark.django_db
def test_password_reset_confirm_used_token_returns_opaque_400(api_client, regular_user):
    token = _issue_token(regular_user)
    token.is_used = True
    token.save(update_fields=["is_used"])
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == OPAQUE_RESET_CODE


@pytest.mark.django_db
def test_password_reset_confirm_expired_token_returns_opaque_400(
    api_client, regular_user
):
    token = _issue_token(regular_user)
    PasswordResetToken.objects.filter(pk=token.pk).update(
        created_at=timezone.now()
        - timedelta(seconds=settings.PASSWORD_RESET_TOKEN_TTL + 60)
    )
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == OPAQUE_RESET_CODE


@pytest.mark.django_db
def test_password_reset_confirm_weak_password_does_not_consume_token(
    api_client, regular_user
):
    token = _issue_token(regular_user)
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "12345"},
        format="json",
    )
    assert r.status_code == 400
    assert any(e["field"] == "new_password" for e in r.json()["errors"])
    token.refresh_from_db()
    assert token.is_used is False
    regular_user.refresh_from_db()
    assert regular_user.check_password("UserStrongPass123!")


@pytest.mark.django_db
def test_password_reset_confirm_rejects_non_uuid_token(api_client):
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": "not-a-uuid", "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert r.status_code == 400
    assert any(e["field"] == "token" for e in r.json()["errors"])


@pytest.mark.django_db
def test_password_reset_confirm_missing_fields_returns_structured_400(api_client):
    r = api_client.post(reverse("password_reset_confirm"), data={}, format="json")
    assert r.status_code == 400
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"token", "new_password"} <= fields


@pytest.mark.django_db
def test_password_reset_confirm_redacts_new_password_in_errors(api_client):
    token = "00000000-0000-0000-0000-000000000000"
    r = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": token, "new_password": "12345"},
        format="json",
    )
    assert r.status_code == 400
    for entry in r.json()["errors"]:
        if entry["field"] == "new_password":
            assert entry["value"] == "***"


@pytest.mark.django_db
def test_password_reset_confirm_token_is_single_use(api_client, regular_user):
    token = _issue_token(regular_user)
    first = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "BrandNewPass123!"},
        format="json",
    )
    assert first.status_code == 200
    second = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": str(token.token), "new_password": "AnotherPass456!"},
        format="json",
    )
    assert second.status_code == 400
    assert second.json()["code"] == OPAQUE_RESET_CODE


# Self-service password-change tests removed in Story 6 — the single-step
# /api/auth/password-change/ endpoint was deleted in favor of the two-step
# /api/profile/password-change/{request,confirm}/ flow. Equivalent test
# coverage now lives in tests/api_tests/test_rbac_user_profile.py under
# TestPasswordChangeRequest / TestPasswordChangeConfirm.


# ---------------- Password recovery: admin reset ----------------


@pytest.mark.django_db
def test_admin_password_reset_superadmin_succeeds(
    api_client, superadmin_user, regular_user
):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    # Pre-create an outstanding refresh for the target so the blacklist
    # invariant has something to act on.
    RefreshToken.for_user(regular_user)
    r = api_client.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": "AdminSet123!"},
        format="json",
    )
    assert r.status_code == 204
    regular_user.refresh_from_db()
    assert regular_user.check_password("AdminSet123!")
    assert BlacklistedToken.objects.filter(token__user=regular_user).exists()


@pytest.mark.django_db
def test_admin_password_reset_non_superadmin_returns_403(auth_client, regular_user):
    """Non-superadmin is rejected at the IsSuperadmin permission class layer
    with the project's standard 403 envelope (code: permission_denied). The
    in-service is_superadmin check inside admin_reset stays as defense-in-depth
    but is unreachable in normal flows.
    """
    r = auth_client.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": "AdminSet123!"},
        format="json",
    )
    assert r.status_code == 403
    assert r.json()["code"] == "permission_denied"
    regular_user.refresh_from_db()
    assert regular_user.check_password("UserStrongPass123!")


@pytest.mark.django_db
def test_admin_password_reset_requires_authentication(api_client, regular_user):
    r = api_client.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": "AdminSet123!"},
        format="json",
    )
    assert r.status_code == 401


@pytest.mark.django_db
def test_admin_password_reset_unknown_user_returns_404(api_client, superadmin_user):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    r = api_client.post(
        reverse("admin_password_reset"),
        data={"user_id": 999_999, "new_password": "AdminSet123!"},
        format="json",
    )
    assert r.status_code == 404
    assert r.json()["code"] == "user_not_found"


@pytest.mark.django_db
def test_admin_password_reset_weak_password_returns_structured_400(
    api_client, superadmin_user, regular_user
):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    r = api_client.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.id, "new_password": "12345"},
        format="json",
    )
    assert r.status_code == 400
    assert any(e["field"] == "new_password" for e in r.json()["errors"])
    regular_user.refresh_from_db()
    assert regular_user.check_password("UserStrongPass123!")


@pytest.mark.django_db
def test_admin_password_reset_validates_user_id_shape(api_client, superadmin_user):
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    r = api_client.post(
        reverse("admin_password_reset"),
        data={"user_id": "not-an-int", "new_password": "AdminSet123!"},
        format="json",
    )
    assert r.status_code == 400
    fields = {e["field"] for e in r.json()["errors"]}
    assert "user_id" in fields


# ------------------------------------------------------------------
# PrintableAsciiPasswordValidator — unit tests (EST-2418)
# ------------------------------------------------------------------
from django.core.exceptions import ValidationError as _DjangoValidationError

from tables.services.rbac.utils.printable_ascii_password_validator import (
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


# ------------------------------------------------------------------
# Password alphabet — integration tests across all 4 endpoints (EST-2418)
# ------------------------------------------------------------------

_BAD_PASSWORDS = [
    "        ",
    "abcd 1234",
    " abcd1234",
    "abcd1234 ",
    "abcd\t1234",
    "abcd\n1234",
    "Pässwörd1",
    "♫abcd1234",
    "emoji😀1234",
    "abc​1234",
    "abc\x7f1234",
]

_REJECTION_SUBSTRING = "only Latin letters, digits, and standard ASCII symbols"


def _assert_password_rejected(response):
    assert response.status_code == 400, response.content
    body = response.json()
    assert body["code"] == "invalid"
    password_errors = [
        e for e in body["errors"] if e["field"] in ("password", "new_password")
    ]
    assert password_errors, body
    assert any(_REJECTION_SUBSTRING in e["reason"] for e in password_errors), body


@pytest.mark.django_db
class TestFirstSetupPasswordAlphabet:
    """POST /api/auth/first-setup/ rejects passwords outside the alphabet."""

    @pytest.mark.parametrize("password", _BAD_PASSWORDS)
    def test_rejects(self, api_client, password):
        get_user_model().objects.all().delete()
        r = api_client.post(
            reverse("first_setup"),
            data={"email": "admin@acme.com", "password": password},
            format="json",
        )
        _assert_password_rejected(r)

    def test_accepts_symbol_password(self, api_client):
        get_user_model().objects.all().delete()
        r = api_client.post(
            reverse("first_setup"),
            data={"email": "admin@acme.com", "password": "P@ssw0rd!9"},
            format="json",
        )
        assert r.status_code == 201, r.content


@pytest.mark.django_db
class TestPasswordResetConfirmAlphabet:
    """POST /api/auth/password-reset/confirm/ rejects passwords outside the alphabet."""

    @pytest.mark.parametrize("password", _BAD_PASSWORDS)
    def test_rejects(self, api_client, regular_user, password):
        token = _issue_token(regular_user)
        r = api_client.post(
            reverse("password_reset_confirm"),
            data={"token": str(token.token), "new_password": password},
            format="json",
        )
        _assert_password_rejected(r)


# TestPasswordChangeAlphabet removed in Story 6 — single-step password-change
# endpoint was deleted. Alphabet enforcement is still covered for the
# admin-reset and password-reset confirm endpoints (below and above) and for
# the two-step profile flow in tests/api_tests/test_rbac_user_profile.py
# (TestPasswordChangeConfirm.test_weak_new_password_returns_400).


@pytest.mark.django_db
class TestAdminPasswordResetAlphabet:
    """POST /api/auth/admin/password-reset/ rejects passwords outside the alphabet."""

    @pytest.mark.parametrize("password", _BAD_PASSWORDS)
    def test_rejects(self, api_client, superadmin_user, regular_user, password):
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
        )
        r = api_client.post(
            reverse("admin_password_reset"),
            data={"user_id": regular_user.id, "new_password": password},
            format="json",
        )
        _assert_password_rejected(r)


# ------------------------------------------------------------------
# Email whitespace + throttle non-string guard (EST-2418)
# ------------------------------------------------------------------

_BAD_EMAILS_WHITESPACE = [
    "user @example.com",
    " user@example.com",
    "user@example.com\n",
    "user@\texample.com",
]


@pytest.mark.django_db
class TestEmailWhitespaceRejection:
    """Email field rejects whitespace at endpoints that validate email."""

    @pytest.mark.parametrize("email", _BAD_EMAILS_WHITESPACE)
    def test_first_setup_rejects(self, api_client, email):
        get_user_model().objects.all().delete()
        r = api_client.post(
            reverse("first_setup"),
            data={"email": email, "password": "P@ssw0rd!9"},
            format="json",
        )
        assert r.status_code == 400, r.content
        body = r.json()
        email_errors = [e for e in body["errors"] if e["field"] == "email"]
        assert email_errors
        assert any(
            "must not contain whitespace" in e["reason"].lower() for e in email_errors
        ), body

    @pytest.mark.parametrize("email", _BAD_EMAILS_WHITESPACE)
    def test_password_reset_request_rejects(self, api_client, email):
        cache.clear()
        r = api_client.post(
            reverse("password_reset_request"),
            data={"email": email},
            format="json",
        )
        assert r.status_code == 400, r.content
        body = r.json()
        email_errors = [e for e in body["errors"] if e["field"] == "email"]
        assert email_errors
        assert any(
            "must not contain whitespace" in e["reason"].lower() for e in email_errors
        ), body


@pytest.mark.django_db
class TestPasswordResetRequestThrottleNonString:
    """POST /api/auth/password-reset/request/ returns 400 (not 500) for non-string email."""

    @pytest.mark.parametrize("bad_value", [123, ["x@y.com"], {"a": 1}, True])
    def test_non_string_email_returns_400(self, api_client, bad_value):
        cache.clear()
        r = api_client.post(
            reverse("password_reset_request"),
            data={"email": bad_value},
            format="json",
        )
        assert r.status_code == 400, r.content
        body = r.json()
        email_errors = [e for e in body["errors"] if e["field"] == "email"]
        assert email_errors
        assert any(
            "must be a string" in e["reason"].lower() for e in email_errors
        ), body
