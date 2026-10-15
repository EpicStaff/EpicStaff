"""API keys on the admin surface: writes are JWT-only, the SYSTEM key is
rejected outright, a USER key may still read with its owner's permissions."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.access.gates import DenyApiKeyAuth, RestrictApiKeyToUserKeyReads
from rbac.models import ApiKey, Organization, OrganizationUser, Role

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ROLES_URL = "/api/admin/roles/"
MEMBERSHIPS_URL = "/api/admin/memberships/"
USERS_URL = "/api/admin/users/"
API_KEYS_URL = "/api/admin/api-keys/"


@pytest.fixture
def system_key_client(issue_api_key):
    raw_key, _ = issue_api_key(user=None, name="system-admin-surface")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


@pytest.fixture
def user_key_client(issue_api_key):
    def _make(user):
        raw_key, _ = issue_api_key(user=user, name="user-admin-surface")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        return client

    return _make


@pytest.fixture
def superadmin_jwt_client(superadmin):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin).access_token}"
    )
    return client


@pytest.fixture
def custom_role(acme):
    return Role.objects.create(name="Disposable", org=acme, is_built_in=False)


@pytest.fixture
def outsider(django_user_model):
    return django_user_model.objects.create_user(
        email="outsider-gate@example.com", password="StrongPass123!"
    )


@pytest.fixture
def member_membership(member_only, acme):
    return OrganizationUser.objects.get(user=member_only, org=acme)


SYSTEM_KEY_REJECTED = RestrictApiKeyToUserKeyReads.non_user_key_message
API_KEY_WRITE_REJECTED = RestrictApiKeyToUserKeyReads.write_message
JWT_ONLY_ENDPOINT = DenyApiKeyAuth.message


def _assert_forbidden(response, expected_message):
    """Pin the gate that refused, not just the status: another gate's 403
    (door gate, IsSuperadmin) carries a different message."""
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    body = response.json()
    assert body["code"] == "permission_denied"
    assert body["message"] == expected_message


# ---- SYSTEM key: rejected, stored state untouched ----


@pytest.mark.django_db
def test_system_key_cannot_create_role(system_key_client, acme):
    response = system_key_client.post(
        ROLES_URL, {"org_id": acme.id, "name": "SysMade", "permissions": []}, format="json"
    )
    _assert_forbidden(response, SYSTEM_KEY_REJECTED)
    assert not Role.objects.filter(name="SysMade").exists()


@pytest.mark.django_db
def test_system_key_cannot_delete_role(system_key_client, custom_role):
    _assert_forbidden(
        system_key_client.delete(f"{ROLES_URL}{custom_role.id}/"), SYSTEM_KEY_REJECTED
    )
    assert Role.objects.filter(pk=custom_role.id).exists()


@pytest.mark.django_db
def test_system_key_cannot_create_membership(system_key_client, acme, outsider, role_member):
    response = system_key_client.post(
        MEMBERSHIPS_URL,
        {"org_id": acme.id, "user_id": outsider.id, "role_id": role_member.id},
        format="json",
    )
    _assert_forbidden(response, SYSTEM_KEY_REJECTED)
    assert not OrganizationUser.objects.filter(user=outsider).exists()


@pytest.mark.django_db
def test_system_key_cannot_change_membership_role(
    system_key_client, member_membership, role_member, role_viewer
):
    response = system_key_client.patch(
        f"{MEMBERSHIPS_URL}{member_membership.id}/", {"role_id": role_viewer.id}, format="json"
    )
    _assert_forbidden(response, SYSTEM_KEY_REJECTED)
    member_membership.refresh_from_db()
    assert member_membership.role_id == role_member.id


@pytest.mark.django_db
def test_system_key_cannot_deactivate_organization(system_key_client, acme, beta):
    _assert_forbidden(
        system_key_client.post(f"/api/admin/organizations/{acme.id}/deactivate/"),
        SYSTEM_KEY_REJECTED,
    )
    acme.refresh_from_db()
    assert acme.is_active is True


@pytest.mark.django_db
def test_system_key_cannot_create_organization(system_key_client):
    response = system_key_client.post(
        "/api/admin/organizations/", {"name": "SysOrg"}, format="json"
    )
    _assert_forbidden(response, SYSTEM_KEY_REJECTED)
    assert not Organization.objects.filter(name="SysOrg").exists()


@pytest.mark.django_db
def test_system_key_cannot_grant_superadmin(system_key_client, outsider):
    _assert_forbidden(
        system_key_client.post(f"{USERS_URL}{outsider.id}/grant-superadmin/"), SYSTEM_KEY_REJECTED
    )
    outsider.refresh_from_db()
    assert outsider.is_superadmin is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url", [ROLES_URL, MEMBERSHIPS_URL, "/api/admin/organizations/", USERS_URL]
)
def test_system_key_cannot_read_admin_surface(system_key_client, url):
    _assert_forbidden(system_key_client.get(url), SYSTEM_KEY_REJECTED)


@pytest.mark.django_db
def test_system_key_cannot_reset_users(system_key_client, superadmin, django_user_model):
    response = system_key_client.post(
        "/api/auth/reset-user/",
        {"email": "taken-over@example.com", "password": "StrongPass123!"},
        format="json",
    )
    _assert_forbidden(response, JWT_ONLY_ENDPOINT)
    assert django_user_model.objects.filter(pk=superadmin.pk).exists()
    assert not django_user_model.objects.filter(email="taken-over@example.com").exists()


@pytest.mark.django_db
def test_system_key_cannot_admin_reset_password(system_key_client, outsider):
    response = system_key_client.post(
        "/api/auth/admin/password-reset/",
        {"user_id": outsider.id, "new_password": "BrandNewPass123!"},
        format="json",
    )
    _assert_forbidden(response, JWT_ONLY_ENDPOINT)
    outsider.refresh_from_db()
    assert outsider.check_password("StrongPass123!")


# ---- USER key: reads keep working, writes are JWT-only ----


@pytest.mark.django_db
def test_user_key_can_still_list_roles(user_key_client, admin_acme, custom_role):
    response = user_key_client(admin_acme).get(ROLES_URL)
    assert response.status_code == status.HTTP_200_OK
    assert custom_role.id in {row["id"] for row in response.json()["results"]}


@pytest.mark.django_db
def test_user_key_cannot_create_role_even_with_roles_create(user_key_client, admin_acme, acme):
    response = user_key_client(admin_acme).post(
        ROLES_URL, {"org_id": acme.id, "name": "KeyMade", "permissions": []}, format="json"
    )
    _assert_forbidden(response, API_KEY_WRITE_REJECTED)
    assert not Role.objects.filter(name="KeyMade").exists()


@pytest.mark.django_db
def test_superadmin_user_key_cannot_reset_users(user_key_client, superadmin, django_user_model):
    response = user_key_client(superadmin).post(
        "/api/auth/reset-user/",
        {"email": "taken-over@example.com", "password": "StrongPass123!"},
        format="json",
    )
    _assert_forbidden(response, JWT_ONLY_ENDPOINT)
    assert django_user_model.objects.filter(pk=superadmin.pk).exists()


@pytest.mark.django_db
def test_superadmin_user_key_cannot_grant_superadmin(user_key_client, superadmin, outsider):
    _assert_forbidden(
        user_key_client(superadmin).post(f"{USERS_URL}{outsider.id}/grant-superadmin/"),
        API_KEY_WRITE_REJECTED,
    )
    outsider.refresh_from_db()
    assert outsider.is_superadmin is False


# ---- /api/admin/api-keys/: the base gate answers first, DenyApiKeyAuth covers USER-key reads ----


@pytest.fixture
def member_key(issue_api_key, member_only):
    _, key = issue_api_key(user=member_only, name="member-target")
    return key


@pytest.mark.django_db
def test_system_key_cannot_list_api_keys(system_key_client):
    _assert_forbidden(system_key_client.get(API_KEYS_URL), SYSTEM_KEY_REJECTED)


@pytest.mark.django_db
def test_user_key_cannot_list_api_keys(user_key_client, admin_acme):
    _assert_forbidden(user_key_client(admin_acme).get(API_KEYS_URL), JWT_ONLY_ENDPOINT)


@pytest.mark.django_db
def test_user_key_cannot_revoke_api_key(user_key_client, admin_acme, member_key):
    _assert_forbidden(
        user_key_client(admin_acme).post(f"{API_KEYS_URL}{member_key.id}/revoke/"),
        API_KEY_WRITE_REJECTED,
    )
    member_key.refresh_from_db()
    assert member_key.revoked_at is None


@pytest.mark.django_db
def test_system_key_cannot_delete_api_key(system_key_client, member_key):
    _assert_forbidden(
        system_key_client.delete(f"{API_KEYS_URL}{member_key.id}/"), SYSTEM_KEY_REJECTED
    )
    assert ApiKey.objects.filter(pk=member_key.pk).exists()


# ---- superadmin JWT: the same five writes still succeed ----


@pytest.mark.django_db
def test_superadmin_jwt_creates_role(superadmin_jwt_client, acme):
    response = superadmin_jwt_client.post(
        ROLES_URL, {"org_id": acme.id, "name": "JwtMade", "permissions": []}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Role.objects.filter(name="JwtMade", org=acme).exists()


@pytest.mark.django_db
def test_superadmin_jwt_deletes_role(superadmin_jwt_client, custom_role):
    response = superadmin_jwt_client.delete(f"{ROLES_URL}{custom_role.id}/")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert not Role.objects.filter(pk=custom_role.id).exists()


@pytest.mark.django_db
def test_superadmin_jwt_creates_membership(superadmin_jwt_client, acme, outsider, role_member):
    response = superadmin_jwt_client.post(
        MEMBERSHIPS_URL,
        {"org_id": acme.id, "user_id": outsider.id, "role_id": role_member.id},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert OrganizationUser.objects.get(user=outsider, org=acme).role_id == role_member.id


@pytest.mark.django_db
def test_superadmin_jwt_changes_membership_role(
    superadmin_jwt_client, member_membership, role_viewer
):
    response = superadmin_jwt_client.patch(
        f"{MEMBERSHIPS_URL}{member_membership.id}/", {"role_id": role_viewer.id}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    member_membership.refresh_from_db()
    assert member_membership.role_id == role_viewer.id


@pytest.mark.django_db
def test_superadmin_jwt_deactivates_organization(superadmin_jwt_client, acme, beta):
    response = superadmin_jwt_client.post(f"/api/admin/organizations/{acme.id}/deactivate/")
    assert response.status_code == status.HTTP_200_OK, response.content
    acme.refresh_from_db()
    assert acme.is_active is False
