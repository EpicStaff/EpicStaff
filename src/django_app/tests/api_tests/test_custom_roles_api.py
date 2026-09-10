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
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


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
    auth_client, admin_acme, acme, role_viewer, django_user_model
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
    assert OrganizationUser.objects.get(user=victim, org=acme).role_id == role_viewer.id


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


# ---- QA: writes must not confirm a role the read surface denies ----


@pytest.fixture
def admin_beta_member_acme(
    db, django_user_model, acme, beta, role_org_admin, role_member
):
    """Org Admin of beta (clears the ROLES door gate) and a plain Member of
    acme (no ROLES bits there) — the caller shape from the QA report."""
    user = django_user_model.objects.create_user(
        email="admin-beta-member-acme@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_patch_role_without_roles_bits_in_its_org_is_404(
    auth_client, admin_beta_member_acme, acme
):
    target = Role.objects.create(name="Hidden-patch-api", org=acme, is_built_in=False)

    resp = auth_client(admin_beta_member_acme).patch(
        f"/api/admin/roles/{target.id}/", {"name": "X"}, format="json"
    )

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "role_not_found"
    assert Role.objects.get(pk=target.id).name == "Hidden-patch-api"


@pytest.mark.django_db
def test_delete_role_without_roles_bits_in_its_org_is_404(
    auth_client, admin_beta_member_acme, acme
):
    target = Role.objects.create(name="Hidden-del-api", org=acme, is_built_in=False)

    resp = auth_client(admin_beta_member_acme).delete(f"/api/admin/roles/{target.id}/")

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "role_not_found"
    assert Role.objects.filter(pk=target.id).exists()


@pytest.mark.django_db
def test_get_and_patch_agree_on_an_invisible_role(
    auth_client, admin_beta_member_acme, acme
):
    """The bug QA reported: GET said 404 while PATCH said 403, confirming an
    id the read surface denies."""
    target = Role.objects.create(name="Hidden-agree-api", org=acme, is_built_in=False)
    client = auth_client(admin_beta_member_acme)

    read = client.get(f"/api/admin/roles/{target.id}/")
    write = client.patch(f"/api/admin/roles/{target.id}/", {"name": "X"}, format="json")

    assert read.status_code == write.status_code == status.HTTP_404_NOT_FOUND
    assert read.json()["code"] == write.json()["code"] == "role_not_found"


@pytest.mark.django_db
def test_patch_role_with_read_but_no_update_is_403(
    auth_client, django_user_model, acme, beta, role_org_admin
):
    """READ makes the role visible, so a missing UPDATE stays an honest 403.

    The caller is Org Admin of beta so the coarse door gate passes on UPDATE;
    the 403 therefore comes from the per-org check in RoleManagementService,
    which is the branch under test.
    """
    reader_role = Role.objects.create(
        name="ReaderOnly-api", org=acme, is_built_in=False
    )
    RolePermission.objects.create(
        role=reader_role, resource_type="roles", permissions=int(Permission.READ)
    )
    reader = django_user_model.objects.create_user(
        email="reader-only-api@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=reader, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=reader, org=acme, role=reader_role)
    target = Role.objects.create(name="Visible-api", org=acme, is_built_in=False)

    resp = auth_client(reader).patch(
        f"/api/admin/roles/{target.id}/", {"name": "X"}, format="json"
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "permission_denied"


# ---- ?assignable_org_ids= : only roles the caller may actually assign ----
#
# Same response shape as the unfiltered call; the parameter is opt-in so the
# Roles management list is unaffected. Parsed exactly like ?org_ids=.

ROLES_URL = "/api/admin/roles/"


def _names(payload, key):
    return {row["name"] for row in payload[key]}


@pytest.fixture
def member_manager(db, django_user_model, acme, beta, role_org_admin):
    """Delegated admin of acme holding only the admin resources, plus Org Admin
    of beta so the door gate passes."""
    role = Role.objects.create(name="Member Manager-af", org=acme, is_built_in=False)
    for resource in ("memberships", "roles"):
        RolePermission.objects.create(
            role=role,
            resource_type=resource,
            permissions=int(
                Permission.CREATE
                | Permission.READ
                | Permission.UPDATE
                | Permission.DELETE
            ),
        )
    user = django_user_model.objects.create_user(
        email="member-manager-af@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


@pytest.mark.django_db
def test_assignable_filter_excludes_every_built_in_for_an_admin_only_role(
    auth_client, member_manager, acme
):
    """An admin-only role holds none of the workspace bits the built-ins grant,
    so all four are filtered out — the visible form of the accepted consequence
    that such a role cannot onboard anyone.

    Its own role is still offered: equal bits are within the ceiling.
    """
    resp = auth_client(member_manager).get(f"{ROLES_URL}?assignable_org_ids={acme.id}")

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["built_in_roles"] == []
    assert _names(body, "results") == {"Member Manager-af"}


@pytest.mark.django_db
def test_assignable_filter_excludes_the_superadmin_role(auth_client, admin_acme, acme):
    """The Superadmin role carries zero permission rows, so the ceiling alone
    would consider it assignable — only the structural guard removes it."""
    resp = auth_client(admin_acme).get(f"{ROLES_URL}?assignable_org_ids={acme.id}")

    names = _names(resp.json(), "built_in_roles")
    assert "Superadmin" not in names
    assert {"Org Admin", "Member", "Viewer"} <= names


@pytest.mark.django_db
def test_unfiltered_list_still_returns_all_four_built_ins(auth_client, admin_acme):
    """The management-list contract: without the parameter nothing is filtered."""
    resp = auth_client(admin_acme).get(ROLES_URL)

    assert _names(resp.json(), "built_in_roles") == {
        "Superadmin",
        "Org Admin",
        "Member",
        "Viewer",
    }


@pytest.mark.django_db
def test_assignable_filter_unions_across_requested_orgs(
    auth_client, django_user_model, acme, beta, role_org_admin
):
    """Org Admin of acme, roles-reader in beta. A built-in is included when it
    is assignable in at least one requested org, matching how ?org_ids= unions."""
    reader = Role.objects.create(name="Roles Reader-af", org=beta, is_built_in=False)
    RolePermission.objects.create(
        role=reader, resource_type="roles", permissions=int(Permission.READ)
    )
    user = django_user_model.objects.create_user(
        email="union-af@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=reader)
    client = auth_client(user)

    both = client.get(f"{ROLES_URL}?assignable_org_ids={acme.id},{beta.id}").json()
    beta_only = client.get(f"{ROLES_URL}?assignable_org_ids={beta.id}").json()

    assert "Org Admin" in _names(both, "built_in_roles")
    assert "Org Admin" not in _names(beta_only, "built_in_roles")


@pytest.mark.django_db
def test_assignable_filter_compares_custom_roles_against_their_own_org(
    auth_client, django_user_model, acme, beta, role_org_admin
):
    """Every custom role belongs to one org, so each is compared there."""
    reader = Role.objects.create(name="Roles Reader-af2", org=beta, is_built_in=False)
    RolePermission.objects.create(
        role=reader, resource_type="roles", permissions=int(Permission.READ)
    )
    user = django_user_model.objects.create_user(
        email="own-org-af@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=reader)

    in_acme = Role.objects.create(name="Acme Helper-af", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=in_acme, resource_type="flows", permissions=int(Permission.READ)
    )
    in_beta = Role.objects.create(name="Beta Power-af", org=beta, is_built_in=False)
    RolePermission.objects.create(
        role=in_beta, resource_type="flows", permissions=int(Permission.CREATE)
    )

    body = (
        auth_client(user)
        .get(f"{ROLES_URL}?assignable_org_ids={acme.id},{beta.id}")
        .json()
    )

    names = _names(body, "results")
    assert "Acme Helper-af" in names  # within the caller's acme bits
    assert "Beta Power-af" not in names  # above the caller's beta bits


@pytest.mark.django_db
def test_assignable_filter_does_not_filter_for_superadmin(
    auth_client, superadmin_user, acme
):
    resp = auth_client(superadmin_user).get(f"{ROLES_URL}?assignable_org_ids={acme.id}")

    assert _names(resp.json(), "built_in_roles") == {
        "Superadmin",
        "Org Admin",
        "Member",
        "Viewer",
    }


@pytest.mark.django_db
def test_assignable_filter_response_shape_is_unchanged(auth_client, admin_acme, acme):
    plain = auth_client(admin_acme).get(ROLES_URL).json()
    filtered = (
        auth_client(admin_acme).get(f"{ROLES_URL}?assignable_org_ids={acme.id}").json()
    )

    assert set(plain.keys()) == set(filtered.keys())


@pytest.mark.django_db
def test_assignable_filter_non_integer_is_400(auth_client, admin_acme):
    resp = auth_client(admin_acme).get(f"{ROLES_URL}?assignable_org_ids=abc")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "org_context_required"


@pytest.mark.django_db
def test_assignable_filter_forbidden_org_is_403(auth_client, admin_acme, beta):
    """Same fail-loud posture as a forbidden ?org_ids= entry."""
    resp = auth_client(admin_acme).get(f"{ROLES_URL}?assignable_org_ids={beta.id}")

    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_assignable_org_ids_supersedes_org_ids(auth_client, member_manager, acme, beta):
    """When both are given the assignable parameter defines the scope, so the
    result is the filtered one rather than beta's unfiltered rows."""
    resp = auth_client(member_manager).get(
        f"{ROLES_URL}?org_ids={beta.id}&assignable_org_ids={acme.id}"
    )

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["built_in_roles"] == []
