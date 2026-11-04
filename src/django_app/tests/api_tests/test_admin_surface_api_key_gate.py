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
def user_key_client(issue_api_key, acme):
    def _make(user):
        raw_key, _ = issue_api_key(user=user, org=acme, name="user-admin-surface")
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


@pytest.fixture
def member_key(issue_api_key, member_only):
    _, key = issue_api_key(user=member_only, name="member-target")
    return key


def _org_active(f):
    f("acme").refresh_from_db()
    return f("acme").is_active


def _membership_role(f):
    f("member_membership").refresh_from_db()
    return f("member_membership").role_id


def _is_superadmin(f):
    f("outsider").refresh_from_db()
    return f("outsider").is_superadmin


def _key_revoked(f):
    f("member_key").refresh_from_db()
    return f("member_key").revoked_at is not None


# Each admin write: the request, and the state it changes (read before and after).
WRITES = {
    "create-role": (
        lambda c, f: c.post(ROLES_URL, {"org_id": f("acme").id, "name": "Made", "permissions": []}, format="json"),
        lambda f: Role.objects.filter(name="Made").exists(),
    ),
    "delete-role": (
        lambda c, f: c.delete(f"{ROLES_URL}{f('custom_role').id}/"),
        lambda f: Role.objects.filter(pk=f("custom_role").id).exists(),
    ),
    "create-membership": (
        lambda c, f: c.post(
            MEMBERSHIPS_URL,
            {"org_id": f("acme").id, "user_id": f("outsider").id, "role_id": f("role_member").id},
            format="json",
        ),
        lambda f: OrganizationUser.objects.filter(user=f("outsider")).exists(),
    ),
    "change-membership-role": (
        lambda c, f: c.patch(f"{MEMBERSHIPS_URL}{f('member_membership').id}/", {"role_id": f("role_viewer").id}, format="json"),
        _membership_role,
    ),
    "deactivate-organization": (
        # beta exists, so acme is not the last active organization.
        lambda c, f: f("beta") and c.post(f"/api/admin/organizations/{f('acme').id}/deactivate/"),
        _org_active,
    ),
    "create-organization": (
        lambda c, f: c.post("/api/admin/organizations/", {"name": "SysOrg"}, format="json"),
        lambda f: Organization.objects.filter(name="SysOrg").exists(),
    ),
    "grant-superadmin": (
        lambda c, f: c.post(f"{USERS_URL}{f('outsider').id}/grant-superadmin/"),
        _is_superadmin,
    ),
    "reset-users": (
        lambda c, f: c.post(
            "/api/auth/reset-user/", {"email": "taken-over@example.com", "password": "StrongPass123!"}, format="json"
        ),
        lambda f: f("django_user_model").objects.filter(email="taken-over@example.com").exists(),
    ),
    "admin-reset-password": (
        lambda c, f: c.post(
            "/api/auth/admin/password-reset/", {"user_id": f("outsider").id, "new_password": "BrandNewPass123!"}, format="json"
        ),
        lambda f: f("outsider").__class__.objects.get(pk=f("outsider").pk).check_password("StrongPass123!"),
    ),
    "revoke-api-key": (lambda c, f: c.post(f"{API_KEYS_URL}{f('member_key').id}/revoke/"), _key_revoked),
    "delete-api-key": (
        lambda c, f: c.delete(f"{API_KEYS_URL}{f('member_key').id}/"),
        lambda f: ApiKey.objects.filter(pk=f("member_key").pk).exists(),
    ),
}

READS = {
    "roles": lambda c, f: c.get(ROLES_URL),
    "memberships": lambda c, f: c.get(MEMBERSHIPS_URL),
    "organizations": lambda c, f: c.get("/api/admin/organizations/"),
    "users": lambda c, f: c.get(USERS_URL),
    "api-keys": lambda c, f: c.get(API_KEYS_URL),
}


def _client(request, caller):
    if caller == "system-key":
        return request.getfixturevalue("system_key_client")
    user = request.getfixturevalue("superadmin" if caller == "superadmin-user-key" else "admin_acme")
    return request.getfixturevalue("user_key_client")(user)


REFUSED = [
    # The SYSTEM key is refused on the whole admin surface.
    *[("system-key", "write", name, SYSTEM_KEY_REJECTED) for name in WRITES if name not in ("reset-users", "admin-reset-password", "revoke-api-key")],
    *[("system-key", "write", name, JWT_ONLY_ENDPOINT) for name in ("reset-users", "admin-reset-password")],
    *[("system-key", "read", name, SYSTEM_KEY_REJECTED) for name in READS],
    # A USER key may read with its owner's permissions, but every write is JWT-only --
    # even for an org admin who holds roles:create, even for a superadmin.
    ("admin-user-key", "write", "create-role", API_KEY_WRITE_REJECTED),
    ("admin-user-key", "write", "revoke-api-key", API_KEY_WRITE_REJECTED),
    ("admin-user-key", "read", "api-keys", JWT_ONLY_ENDPOINT),
    ("superadmin-user-key", "write", "reset-users", JWT_ONLY_ENDPOINT),
    ("superadmin-user-key", "write", "grant-superadmin", API_KEY_WRITE_REJECTED),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "kind", "name", "message"), REFUSED, ids=[f"{caller}-{kind}-{name}" for caller, kind, name, _ in REFUSED]
)
def test_api_key_on_the_admin_surface_is_refused_and_changes_nothing(request, caller, kind, name, message):
    f = request.getfixturevalue
    client = _client(request, caller)
    if kind == "read":
        _assert_forbidden(READS[name](client, f), message)
        return
    send, state = WRITES[name]
    before = state(f)

    _assert_forbidden(send(client, f), message)

    assert state(f) == before
    assert f("django_user_model").objects.filter(pk=f("superadmin").pk).exists()


@pytest.mark.django_db
def test_user_key_can_still_list_roles(user_key_client, admin_acme, custom_role):
    response = user_key_client(admin_acme).get(ROLES_URL)
    assert response.status_code == status.HTTP_200_OK
    assert custom_role.id in {row["id"] for row in response.json()["results"]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "expected_status"),
    [
        ("create-role", status.HTTP_201_CREATED),
        ("delete-role", status.HTTP_200_OK),
        ("create-membership", status.HTTP_201_CREATED),
        ("change-membership-role", status.HTTP_200_OK),
        ("deactivate-organization", status.HTTP_200_OK),
    ],
)
def test_superadmin_jwt_still_performs_the_write(request, superadmin_jwt_client, name, expected_status):
    f = request.getfixturevalue
    send, state = WRITES[name]
    before = state(f)

    response = send(superadmin_jwt_client, f)

    assert response.status_code == expected_status, response.content
    assert state(f) != before
