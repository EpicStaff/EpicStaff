import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


# ---- shared fixtures ----


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Acme Inc")


@pytest.fixture
def superadmin_user(db, django_user_model):
    return django_user_model.objects.create_superuser(
        email="super@example.com", password="StrongPass123!"
    )


@pytest.fixture
def org_admin_user(db, django_user_model, org_acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_org_admin)
    return user


@pytest.fixture
def member_user(db, django_user_model, org_acme, role_member):
    user = django_user_model.objects.create_user(
        email="member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_member)
    return user


@pytest.fixture
def auth_client():
    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


# ---- Catalog ----


@pytest.mark.django_db
def test_permission_catalog_requires_auth():
    client = APIClient()
    response = client.get("/api/permissions/catalog/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---- Door gates of the admin lists ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "caller", "expected"),
    [
        ("/api/admin/memberships/?org_ids={acme}", "org_admin_user", status.HTTP_200_OK),
        ("/api/admin/memberships/", "member_user", status.HTTP_403_FORBIDDEN),
        ("/api/admin/memberships/", "superadmin_user", status.HTTP_200_OK),
        # Member has roles=0 everywhere; the roles list needs no X-Organization-Id.
        ("/api/admin/roles/", "member_user", status.HTTP_403_FORBIDDEN),
        ("/api/admin/roles/", "org_admin_user", status.HTTP_200_OK),
        # The router rejects a non-numeric pk before dispatch.
        ("/api/admin/roles/test/", "org_admin_user", status.HTTP_404_NOT_FOUND),
    ],
)
def test_admin_list_door_gates(request, auth_client, org_acme, url, caller, expected):
    response = auth_client(request.getfixturevalue(caller)).get(url.format(acme=org_acme.id))

    assert response.status_code == expected


@pytest.mark.django_db
def test_built_in_roles_show_their_permissions(auth_client, org_admin_user, role_member):
    client = auth_client(org_admin_user)

    body = client.get("/api/admin/roles/").json()
    org_admin = next(role for role in body["built_in_roles"] if role["name"] == "Org Admin")
    flows = next(p for p in org_admin["permissions"] if p["resource_type"] == "flows")

    assert set(flows["actions"]) == {"create", "read", "update", "delete", "export", "run"}
    assert client.get(f"/api/admin/roles/{role_member.id}/").json()["name"] == "Member"


# ---- /api/permissions/me/ ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("header", "status_code", "code"),
    [
        (None, status.HTTP_400_BAD_REQUEST, "org_context_required"),
        ("abc", status.HTTP_400_BAD_REQUEST, "org_context_required"),
        ("other", status.HTTP_403_FORBIDDEN, "org_membership_required"),
    ],
    ids=["no-org", "malformed-org", "not-a-member"],
)
def test_permissions_me_needs_an_org_the_caller_belongs_to(auth_client, member_user, header, status_code, code):
    headers = {}
    if header == "other":
        headers["HTTP_X_ORGANIZATION_ID"] = str(Organization.objects.create(name="Other Inc (permissions-me tests)").id)
    elif header:
        headers["HTTP_X_ORGANIZATION_ID"] = header

    response = auth_client(member_user).get("/api/permissions/me/", **headers)

    assert response.status_code == status_code
    assert response.json()["code"] == code


@pytest.mark.django_db
def test_permissions_me_superadmin_star(auth_client, superadmin_user, org_acme):
    response = auth_client(superadmin_user).get("/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(org_acme.id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert (body["is_superadmin"], body["permissions"], body["role"]) == (True, "*", None)


@pytest.mark.django_db
def test_permissions_me_org_admin(auth_client, org_admin_user, org_acme):
    response = auth_client(org_admin_user).get("/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(org_acme.id))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["is_superadmin"] is False
    assert body["role"]["name"] == "Org Admin"
    assert "export" in body["permissions"]["flows"]
    # Org Admin holds organizations READ|UPDATE (rename/manage own org).
    assert body["permissions"]["organizations"] == ["read", "update"]
