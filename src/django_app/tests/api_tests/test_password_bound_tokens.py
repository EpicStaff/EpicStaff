"""Every JWT is bound to the password it was minted under.

A refresh token rotated by `/api/auth/refresh/` has no OutstandingToken row,
so blacklisting cannot reach it. These tests drive a session through a
rotation first, so they only pass if the password binding itself kills it.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from rbac.identity.refresh_cookie import refresh_cookie_name

ORIGINAL_PASSWORD = "UserStrongPass123!"
NEW_PASSWORD = "BrandNewPass456!"
PROFILE_URL = "/api/profile/"


def _logged_in_and_rotated(user) -> tuple[APIClient, str]:
    """Log in, rotate the refresh cookie once, return (client, rotated access)."""
    client = APIClient()
    login = client.post(
        reverse("login"),
        data={"email": user.email, "password": ORIGINAL_PASSWORD},
        format="json",
    )
    assert login.status_code == 200
    rotated = client.post(reverse("refresh"))
    assert rotated.status_code == 200
    return client, rotated.json()["access"]


def _assert_session_dead(client: APIClient, access: str) -> None:
    refresh = client.post(reverse("refresh"))
    assert refresh.status_code == 401
    assert refresh.cookies[refresh_cookie_name()].value == ""

    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert bearer.get(PROFILE_URL).status_code == 401


def _reset_by_link(user, superadmin_user):
    _token_row, raw_token = PasswordResetTokenRepository().create_for_user(user)
    return APIClient().post(
        reverse("password_reset_confirm"), data={"token": raw_token, "new_password": NEW_PASSWORD}, format="json"
    )


def _reset_by_admin(user, superadmin_user):
    admin = APIClient()
    admin.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}")
    return admin.post(
        reverse("admin_password_reset"), data={"user_id": user.id, "new_password": NEW_PASSWORD}, format="json"
    )


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
@pytest.mark.parametrize(("reset", "status_code"), [(_reset_by_link, 200), (_reset_by_admin, 204)], ids=["reset-link", "admin-reset"])
def test_a_password_reset_kills_a_rotated_session(regular_user, superadmin_user, reset, status_code):
    session, access = _logged_in_and_rotated(regular_user)

    assert reset(regular_user, superadmin_user).status_code == status_code
    _assert_session_dead(session, access)


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_password_change_kills_other_sessions_and_keeps_the_fresh_pair(regular_user):
    other_session, other_access = _logged_in_and_rotated(regular_user)
    own_session, own_access = _logged_in_and_rotated(regular_user)
    own_session.credentials(HTTP_AUTHORIZATION=f"Bearer {own_access}")
    ticket = own_session.post(
        reverse("profile_password_change_request"),
        data={"current_password": ORIGINAL_PASSWORD},
        format="json",
    ).json()["ticket"]

    change = own_session.post(
        reverse("profile_password_change_confirm"),
        data={"ticket": ticket, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert change.status_code == 200
    _assert_session_dead(other_session, other_access)
    fresh = APIClient()
    fresh.credentials(HTTP_AUTHORIZATION=f"Bearer {change.json()['access']}")
    assert fresh.get(PROFILE_URL).status_code == 200
    # own_session now carries the cookie set by the change response.
    own_session.credentials()
    assert own_session.post(reverse("refresh")).status_code == 200


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_token_without_password_claim_is_rejected(regular_user):
    """Sessions minted before the binding was enabled must not survive it."""
    refresh = RefreshToken.for_user(regular_user)
    del refresh[api_settings.REVOKE_TOKEN_CLAIM]

    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    assert bearer.get(PROFILE_URL).status_code == 401

    cookie_client = APIClient()
    cookie_client.cookies[refresh_cookie_name()] = str(refresh)
    response = cookie_client.post(reverse("refresh"))
    assert response.status_code == 401
    assert response.cookies[refresh_cookie_name()].value == ""


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_refresh_for_a_deleted_user_is_rejected(regular_user):
    refresh = str(RefreshToken.for_user(regular_user))
    regular_user.delete()

    client = APIClient()
    client.cookies[refresh_cookie_name()] = refresh
    assert client.post(reverse("refresh")).status_code == 401


# ---- token introspection (used by the realtime service's WebSocket auth) ----


def _introspect(system_raw_key: str, token: str) -> dict:
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=system_raw_key)
    response = client.post(reverse("token_introspect"), data={"token": token}, format="json")
    assert response.status_code == 200
    return response.json()


def _new_password(user, token):
    user.set_password(NEW_PASSWORD)
    user.save(update_fields=["password"])
    return str(token.access_token)


def _no_password_claim(user, token):
    del token[api_settings.REVOKE_TOKEN_CLAIM]
    return str(token.access_token)


def _deactivated(user, token):
    user.is_active = False
    user.save(update_fields=["is_active"])
    return str(token.access_token)


def _deleted(user, token):
    access = str(token.access_token)
    user.delete()
    return access


@pytest.mark.django_db
@pytest.mark.parametrize(
    "spoil",
    [_new_password, _no_password_claim, _deactivated, _deleted, lambda user, token: str(token)],
    ids=["previous-password", "no-password-claim", "inactive-user", "deleted-user", "refresh-token"],
)
def test_introspect_reports_unusable_tokens_inactive_and_nothing_else(regular_user, env_api_key, spoil):
    system_raw_key, _system_key = env_api_key
    token = RefreshToken.for_user(regular_user)
    assert _introspect(system_raw_key, str(token.access_token))["active"] is True

    assert _introspect(system_raw_key, spoil(regular_user, token)) == {"active": False}


@pytest.mark.usefixtures("refresh_cookie_secure")
@pytest.mark.django_db
def test_refresh_for_a_deactivated_user_is_rejected_and_clears_the_cookie(regular_user):
    session, _access = _logged_in_and_rotated(regular_user)
    regular_user.is_active = False
    regular_user.save(update_fields=["is_active"])

    response = session.post(reverse("refresh"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Token is invalid or expired."}
    assert response.cookies[refresh_cookie_name()].value == ""
