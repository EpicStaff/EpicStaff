import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- shared fixtures ----


@pytest.fixture
def role_superadmin(db):
    return Role.objects.get(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


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


@pytest.mark.django_db
def test_permission_catalog_returns_actions_and_resource_types(
    member_user, auth_client
):
    response = auth_client(member_user).get("/api/permissions/catalog/")
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert "actions" in body and "resource_types" in body
    action_codes = [a["code"] for a in body["actions"]]
    assert action_codes == [
        "create",
        "read",
        "update",
        "delete",
        "export",
    ]
    resource_codes = [r["code"] for r in body["resource_types"]]
    assert "organizations" in resource_codes
    assert "secrets" in resource_codes
    orgs_entry = next(r for r in body["resource_types"] if r["code"] == "organizations")
    assert orgs_entry["applicable_actions"] == ["create", "read", "update", "delete"]
    assert orgs_entry["group"] == "admin"


# ---- Built-in role seed sanity ----


@pytest.mark.django_db
def test_org_admin_seed_has_flows_export(role_org_admin):
    row = RolePermission.objects.get(role=role_org_admin, resource_type="flows")
    assert row.permissions == 31


@pytest.mark.django_db
def test_member_seed_has_no_users_or_roles(role_member):
    row_users = RolePermission.objects.get(role=role_member, resource_type="users")
    row_roles = RolePermission.objects.get(role=role_member, resource_type="roles")
    assert row_users.permissions == 0
    assert row_roles.permissions == 0


@pytest.mark.django_db
def test_viewer_seed_can_use_flows_and_secrets(role_viewer):
    flows = RolePermission.objects.get(role=role_viewer, resource_type="flows")
    secrets = RolePermission.objects.get(role=role_viewer, resource_type="secrets")
    assert flows.permissions == 66  # R | use
    assert secrets.permissions == 192  # use | list


@pytest.mark.django_db
def test_superadmin_role_has_no_role_permissions(role_superadmin):
    assert not RolePermission.objects.filter(role=role_superadmin).exists()


# ---- HasOrgPermission integration ----


@pytest.mark.django_db
def test_org_users_list_org_admin_allowed(auth_client, org_admin_user, org_acme):
    response = auth_client(org_admin_user).get(
        f"/api/admin/organizations/{org_acme.id}/users/"
    )
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_org_users_list_member_denied(auth_client, member_user, org_acme):
    response = auth_client(member_user).get(
        f"/api/admin/organizations/{org_acme.id}/users/"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_org_users_list_superadmin_allowed(auth_client, superadmin_user, org_acme):
    response = auth_client(superadmin_user).get(
        f"/api/admin/organizations/{org_acme.id}/users/"
    )
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_is_superadmin_or_org_admin_class_removed():
    """Asserts the deprecated class is gone. Regression guard."""
    from tables.services.rbac import permissions as permission_module

    assert not hasattr(permission_module, "IsSuperadminOrOrgAdmin")


# ---- Roles endpoints ----


@pytest.mark.django_db
def test_admin_roles_list_requires_header(auth_client, member_user):
    response = auth_client(member_user).get("/api/admin/roles/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "org_context_required"


@pytest.mark.django_db
def test_admin_roles_list_returns_builtins(auth_client, member_user, org_acme):
    response = auth_client(member_user).get(
        "/api/admin/roles/", HTTP_X_ORGANIZATION_ID=str(org_acme.id)
    )
    assert response.status_code == status.HTTP_200_OK
    names = [r["name"] for r in response.json()]
    assert {"Superadmin", "Org Admin", "Member", "Viewer"}.issubset(set(names))


@pytest.mark.django_db
def test_admin_roles_list_org_admin_role_has_permissions(
    auth_client, member_user, org_acme
):
    response = auth_client(member_user).get(
        "/api/admin/roles/", HTTP_X_ORGANIZATION_ID=str(org_acme.id)
    )
    body = response.json()
    org_admin = next(r for r in body if r["name"] == "Org Admin")
    flows = next(p for p in org_admin["permissions"] if p["resource_type"] == "flows")
    assert set(flows["actions"]) == {"create", "read", "update", "delete", "export"}


@pytest.mark.django_db
def test_admin_role_detail(auth_client, member_user, role_member):
    response = auth_client(member_user).get(f"/api/admin/roles/{role_member.id}/")
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["name"] == "Member"
    assert body["is_built_in"] is True


@pytest.mark.django_db
def test_admin_org_roles_target_context(auth_client, superadmin_user, org_acme):
    response = auth_client(superadmin_user).get(
        f"/api/admin/organizations/{org_acme.id}/roles/"
    )
    assert response.status_code == status.HTTP_200_OK
    names = [r["name"] for r in response.json()]
    assert "Org Admin" in names


@pytest.mark.django_db
def test_admin_org_roles_member_denied(auth_client, member_user, db):
    other = Organization.objects.create(name="Other Inc (role tests)")
    response = auth_client(member_user).get(
        f"/api/admin/organizations/{other.id}/roles/"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_role_detail_non_int_pk_returns_404(auth_client, member_user):
    response = auth_client(member_user).get("/api/admin/roles/test/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "role_not_found"


@pytest.mark.django_db
def test_admin_org_roles_nonexistent_org_returns_404(auth_client, superadmin_user):
    # Superadmin bypasses the membership gate, so a non-existent (but
    # well-formed) org id must 404 rather than silently return the built-ins.
    response = auth_client(superadmin_user).get(
        "/api/admin/organizations/999999/roles/"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "organization_not_found"


# ---- Built-in immutability guard ----


@pytest.mark.django_db
def test_built_in_role_immutable_guard_raises(role_org_admin):
    from tables.services.rbac.role_management_service import RoleManagementService
    from tables.services.rbac.rbac_exceptions import BuiltInRoleImmutableError

    service = RoleManagementService()
    with pytest.raises(BuiltInRoleImmutableError) as exc_info:
        service.assert_mutable(role_org_admin)
    assert exc_info.value.default_code == "built_in_role_immutable"
    assert exc_info.value.status_code == 403


# ---- /api/permissions/me/ ----


@pytest.mark.django_db
def test_permissions_me_missing_header_400(auth_client, member_user):
    response = auth_client(member_user).get("/api/permissions/me/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "org_context_required"


@pytest.mark.django_db
def test_permissions_me_malformed_header_400(auth_client, member_user):
    response = auth_client(member_user).get(
        "/api/permissions/me/", HTTP_X_ORGANIZATION_ID="abc"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "org_context_required"


@pytest.mark.django_db
def test_permissions_me_non_member_403(auth_client, member_user, db):
    other = Organization.objects.create(name="Other Inc (permissions-me tests)")
    response = auth_client(member_user).get(
        "/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(other.id)
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["code"] == "org_membership_required"


@pytest.mark.django_db
def test_permissions_me_superadmin_star(auth_client, superadmin_user, org_acme):
    response = auth_client(superadmin_user).get(
        "/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(org_acme.id)
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["is_superadmin"] is True
    assert body["permissions"] == "*"
    assert body["role"] is None


@pytest.mark.django_db
def test_permissions_me_org_admin(auth_client, org_admin_user, org_acme):
    response = auth_client(org_admin_user).get(
        "/api/permissions/me/", HTTP_X_ORGANIZATION_ID=str(org_acme.id)
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["is_superadmin"] is False
    assert body["role"]["name"] == "Org Admin"
    assert "export" in body["permissions"]["flows"]
    assert body["permissions"]["organizations"] == []
