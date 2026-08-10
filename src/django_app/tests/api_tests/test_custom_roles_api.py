import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def auth_client():
    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


@pytest.fixture
def acme(db):
    return Organization.objects.create(name="Acme-api")


@pytest.fixture
def beta(db):
    return Organization.objects.create(name="Beta-api")


@pytest.fixture
def admin_acme(db, django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-acme@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def member_only(db, django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(
        email="member-only@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_list_denied_without_roles_permission(auth_client, member_only):
    resp = auth_client(member_only).get("/api/admin/roles/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_list_returns_builtins_and_results_shape(auth_client, admin_acme, acme):
    Role.objects.create(name="Billing", org=acme, is_built_in=False)
    body = auth_client(admin_acme).get("/api/admin/roles/").json()
    assert {"built_in_roles", "results", "count"}.issubset(body.keys())
    builtin_names = {r["name"] for r in body["built_in_roles"]}
    assert {"Superadmin", "Org Admin", "Member", "Viewer"} == builtin_names
    assert body["results"][0]["name"] == "Billing"
    assert body["results"][0]["org"] == {"id": acme.id, "name": "Acme-api"}


@pytest.mark.django_db
def test_list_org_ids_forbidden_fails_loud(auth_client, admin_acme, beta):
    resp = auth_client(admin_acme).get(f"/api/admin/roles/?org_ids={beta.id}")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_create_role(auth_client, admin_acme, acme):
    payload = {
        "org_id": acme.id,
        "name": "Billing Manager",
        "description": "manage billing",
        "permissions": [{"resource_type": "secrets", "actions": ["read", "update"]}],
    }
    resp = auth_client(admin_acme).post("/api/admin/roles/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["name"] == "Billing Manager"


@pytest.mark.django_db
def test_create_role_escalation_denied(auth_client, django_user_model, acme):
    manager_role = Role.objects.create(name="RoleMgr-api", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=manager_role,
        resource_type="roles",
        permissions=int(
            Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
        ),
    )
    manager = django_user_model.objects.create_user(
        email="mgr-api@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=manager, org=acme, role=manager_role)
    payload = {
        "org_id": acme.id,
        "name": "Escalate",
        "permissions": [{"resource_type": "secrets", "actions": ["read"]}],
    }
    resp = auth_client(manager).post("/api/admin/roles/", payload, format="json")
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "permission_escalation_denied"


@pytest.mark.django_db
def test_update_builtin_is_403(auth_client, admin_acme, role_member):
    resp = auth_client(admin_acme).patch(
        f"/api/admin/roles/{role_member.id}/", {"name": "X"}, format="json"
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "built_in_role_immutable"


@pytest.mark.django_db
def test_delete_dry_run_then_real(
    auth_client, admin_acme, acme, role_member, django_user_model
):
    custom = Role.objects.create(name="Temp-api", org=acme, is_built_in=False)
    victim = django_user_model.objects.create_user(
        email="victim-api@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=victim, org=acme, role=custom)

    dry = auth_client(admin_acme).delete(f"/api/admin/roles/{custom.id}/?dry_run=true")
    assert dry.status_code == status.HTTP_200_OK
    assert dry.json()["assigned_count"] == 1
    assert Role.objects.filter(pk=custom.id).exists()

    real = auth_client(admin_acme).delete(f"/api/admin/roles/{custom.id}/")
    assert real.status_code == status.HTTP_200_OK
    assert real.json()["reassigned_count"] == 1
    assert not Role.objects.filter(pk=custom.id).exists()
    assert OrganizationUser.objects.get(user=victim, org=acme).role_id == role_member.id


@pytest.mark.django_db
def test_retrieve_cross_org_role_404(auth_client, admin_acme, beta):
    other = Role.objects.create(name="Hidden-api", org=beta, is_built_in=False)
    resp = auth_client(admin_acme).get(f"/api/admin/roles/{other.id}/")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "role_not_found"


@pytest.mark.django_db
def test_list_excludes_orgs_without_roles_read(
    auth_client, django_user_model, role_org_admin, role_member, acme, beta
):
    user = django_user_model.objects.create_user(
        email="cross-iso@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(
        user=user, org=acme, role=role_org_admin
    )  # ROLES CRUD in acme
    OrganizationUser.objects.create(
        user=user, org=beta, role=role_member
    )  # no ROLES in beta
    Role.objects.create(name="AcmeCustom", org=acme, is_built_in=False)
    Role.objects.create(name="BetaCustom", org=beta, is_built_in=False)
    body = auth_client(user).get("/api/admin/roles/").json()
    names = [r["name"] for r in body["results"]]
    assert "AcmeCustom" in names
    assert "BetaCustom" not in names


@pytest.mark.django_db
def test_create_with_create_but_no_read_returns_201(
    auth_client, django_user_model, acme
):
    # Regression (final-review I1): a role granting ROLES=CREATE without READ
    # must not 404 a committed create when the response is built.
    mgr_role = Role.objects.create(name="CreatorOnly", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=mgr_role, resource_type="roles", permissions=int(Permission.CREATE)
    )
    user = django_user_model.objects.create_user(
        email="creator-only@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=mgr_role)
    resp = auth_client(user).post(
        "/api/admin/roles/",
        {"org_id": acme.id, "name": "MadeByCreator", "permissions": []},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["name"] == "MadeByCreator"


@pytest.mark.django_db
def test_builtin_roles_assigned_count_is_zero(
    auth_client, admin_acme, acme, role_member, django_user_model
):
    # Regression (final-review I2): built-in assigned_count must be 0 in the
    # cross-org list, never a global cross-org total.
    other = django_user_model.objects.create_user(
        email="plain-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=other, org=acme, role=role_member)
    body = auth_client(admin_acme).get("/api/admin/roles/").json()
    assert body["built_in_roles"]  # sanity: built-ins are present
    for role in body["built_in_roles"]:
        assert role["assigned_count"] == 0
