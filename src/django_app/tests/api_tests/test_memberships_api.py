import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = "/api/admin/memberships/"


def detail_url(membership_id):
    return f"/api/admin/memberships/{membership_id}/"


# ---- permissions / door gate ----


@pytest.mark.django_db
def test_list_anonymous_401():
    assert APIClient().get(LIST_URL).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_list_denied_without_users_read(client_as, member_only):
    assert client_as(member_only).get(LIST_URL).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_create_denied_without_users_create(
    client_as, member_only, acme, role_member, django_user_model
):
    django_user_model.objects.create_user(email="t@x.com", password="StrongPass123!")
    resp = client_as(member_only).post(
        LIST_URL,
        {"org_id": acme.id, "email": "t@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---- list ----


@pytest.mark.django_db
def test_list_returns_membership_rows(client_as, admin_acme, acme):
    body = client_as(admin_acme).get(LIST_URL).json()
    assert set(body.keys()) == {"count", "next", "previous", "results"}
    row = body["results"][0]
    assert row["org"] == {"id": acme.id, "name": acme.name}
    assert set(row["user"].keys()) == {
        "id",
        "email",
        "display_name",
        "avatar_url",
        "is_active",
    }


@pytest.mark.django_db
def test_list_scoped_to_readable_orgs(
    client_as, admin_acme, acme, beta, django_user_model, role_member
):
    OrganizationUser.objects.create(
        user=django_user_model.objects.create_user(
            email="b@x.com", password="StrongPass123!"
        ),
        org=beta,
        role=role_member,
    )
    body = client_as(admin_acme).get(LIST_URL).json()
    assert {r["org"]["id"] for r in body["results"]} == {acme.id}


@pytest.mark.django_db
def test_list_forbidden_org_ids_403(client_as, admin_acme, beta):
    resp = client_as(admin_acme).get(LIST_URL + f"?org_ids={beta.id}")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["role_id=abc", "status=Active"])
def test_list_rejects_malformed_filters(client_as, admin_acme, query):
    resp = client_as(admin_acme).get(f"{LIST_URL}?{query}")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid"


@pytest.mark.django_db
def test_list_superadmin_sees_all(
    client_as, superadmin, acme, beta, django_user_model, role_member
):
    OrganizationUser.objects.create(
        user=django_user_model.objects.create_user(
            email="b2@x.com", password="StrongPass123!"
        ),
        org=beta,
        role=role_member,
    )
    body = client_as(superadmin).get(LIST_URL).json()
    assert {beta.id}.issubset({r["org"]["id"] for r in body["results"]})


# ---- add ----


@pytest.mark.django_db
@pytest.mark.parametrize("identify_by", ["email", "user_id"])
def test_add_member(client_as, admin_acme, acme, role_member, django_user_model, identify_by):
    target = django_user_model.objects.create_user(email="new@x.com", password="StrongPass123!")
    identity = {"email": target.email} if identify_by == "email" else {"user_id": target.id}

    resp = client_as(admin_acme).post(
        LIST_URL, {"org_id": acme.id, "role_id": role_member.id, **identity}, format="json"
    )

    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["user"]["email"] == "new@x.com"
    assert OrganizationUser.objects.filter(user=target, org=acme, role=role_member).exists()


def _superadmin_role():
    return Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target", "body", "status_code", "code"),
    [
        (None, {"email": "nobody@x.com"}, 404, "user_not_found"),
        ({"member_of_acme": True}, {"email": "t@x.com"}, 400, "membership_already_exists"),
        # An org the caller cannot see is not found, never forbidden.
        ({}, {"email": "t@x.com", "org": "beta"}, 404, None),
        ({}, {}, 400, "invalid"),
        ({}, {"email": "t@x.com", "user_id": "target"}, 400, None),
        ({}, {"email": "t@x.com", "role": "superadmin"}, 400, "invalid_role_assignment"),
        ({"is_superadmin": True}, {"email": "t@x.com"}, 400, "superadmin_not_assignable"),
        ({"is_superadmin": True}, {"user_id": "target"}, 400, "superadmin_not_assignable"),
        ({"is_active": False}, {"email": "t@x.com"}, 400, "user_not_active"),
    ],
    ids=["unknown-email", "already-member", "invisible-org", "no-user", "email-and-user-id",
         "superadmin-role", "superadmin-by-email", "superadmin-by-id", "inactive-user"],
)
def test_add_member_is_refused(
    client_as, admin_acme, acme, beta, role_member, django_user_model, target, body, status_code, code
):
    user = None
    if target is not None:
        member_of_acme = target.pop("member_of_acme", False)
        user = django_user_model.objects.create_user(email="t@x.com", password="StrongPass123!", **target)
        if member_of_acme:
            OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    org = beta if body.pop("org", None) == "beta" else acme
    role = _superadmin_role() if body.pop("role", None) == "superadmin" else role_member
    if body.get("user_id") == "target":
        body["user_id"] = user.id
    memberships_before = OrganizationUser.objects.count()

    resp = client_as(admin_acme).post(LIST_URL, {"org_id": org.id, "role_id": role.id, **body}, format="json")

    assert resp.status_code == status_code
    if code:
        assert resp.json()["code"] == code
    assert OrganizationUser.objects.count() == memberships_before


@pytest.fixture
def membership_manager_acme(db, django_user_model, acme):
    """Holds only MEMBERSHIPS create/read/update in acme — narrow enough that
    the escalation ceiling can refuse a role (Org Admin holds every grantable bit)."""
    role = Role.objects.create(name="MembershipManager", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type="memberships",
        permissions=int(Permission.CREATE | Permission.READ | Permission.UPDATE),
    )
    user = django_user_model.objects.create_user(email="mm@x.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


@pytest.fixture
def foreign_and_missing_role_ids(beta):
    """A custom role of beta and an id no role has — the two must be indistinguishable.

    The foreign role grants a bit `membership_manager_acme` lacks, so running the
    escalation ceiling before the org check would surface as a 403 and fail.
    """
    foreign = Role.objects.create(name="BetaOnly", org=beta, is_built_in=False)
    RolePermission.objects.create(role=foreign, resource_type="flows", permissions=int(Permission.READ))
    missing = Role.objects.order_by("-pk").first().pk + 1000
    return foreign.pk, missing


@pytest.mark.django_db
def test_add_member_foreign_org_role_answers_like_a_missing_role(
    client_as, membership_manager_acme, acme, django_user_model, foreign_and_missing_role_ids
):
    django_user_model.objects.create_user(email="t@x.com", password="StrongPass123!")
    client = client_as(membership_manager_acme)

    foreign, missing = (
        client.post(LIST_URL, {"org_id": acme.id, "email": "t@x.com", "role_id": role_id}, format="json")
        for role_id in foreign_and_missing_role_ids
    )

    assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
    assert foreign.json() == missing.json()
    assert foreign.json()["code"] == "role_not_found"
    assert not OrganizationUser.objects.filter(user__email="t@x.com").exists()


# ---- change role ----


@pytest.mark.django_db
def test_change_role_200(
    client_as, admin_acme, acme, role_member, role_viewer, django_user_model
):
    bob = django_user_model.objects.create_user(
        email="bob@x.com", password="StrongPass123!"
    )
    m = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)
    resp = client_as(admin_acme).patch(
        detail_url(m.id), {"role_id": role_viewer.id}, format="json"
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["role"]["id"] == role_viewer.id


@pytest.mark.django_db
def test_change_role_foreign_org_role_answers_like_a_missing_role(
    client_as, membership_manager_acme, acme, role_member, django_user_model, foreign_and_missing_role_ids
):
    bob = django_user_model.objects.create_user(email="bob@x.com", password="StrongPass123!")
    membership = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)
    client = client_as(membership_manager_acme)

    foreign, missing = (
        client.patch(detail_url(membership.id), {"role_id": role_id}, format="json")
        for role_id in foreign_and_missing_role_ids
    )

    assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
    assert foreign.json() == missing.json()
    assert foreign.json()["code"] == "role_not_found"
    membership.refresh_from_db()
    assert membership.role_id == role_member.id


@pytest.mark.django_db
def test_change_role_to_superadmin_role_400(client_as, admin_acme, acme, role_member, django_user_model):
    bob = django_user_model.objects.create_user(email="bob@x.com", password="StrongPass123!")
    membership = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)

    resp = client_as(admin_acme).patch(detail_url(membership.id), {"role_id": _superadmin_role().id}, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid_role_assignment"
    membership.refresh_from_db()
    assert membership.role_id == role_member.id


@pytest.mark.django_db
def test_change_own_role_403(client_as, admin_acme, acme, role_member):
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    resp = client_as(admin_acme).patch(
        detail_url(own.id), {"role_id": role_member.id}, format="json"
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "cannot_modify_self_membership"


@pytest.mark.django_db
def test_change_cross_org_404(
    client_as, admin_acme, beta, role_member, role_viewer, django_user_model
):
    other = OrganizationUser.objects.create(
        user=django_user_model.objects.create_user(
            email="c@x.com", password="StrongPass123!"
        ),
        org=beta,
        role=role_member,
    )
    resp = client_as(admin_acme).patch(
        detail_url(other.id), {"role_id": role_viewer.id}, format="json"
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_change_non_numeric_pk_404(client_as, admin_acme, role_member):
    resp = client_as(admin_acme).patch(
        "/api/admin/memberships/abc/", {"role_id": role_member.id}, format="json"
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---- remove ----


@pytest.mark.django_db
def test_remove_204(client_as, admin_acme, acme, role_member, django_user_model):
    bob = django_user_model.objects.create_user(
        email="rm@x.com", password="StrongPass123!"
    )
    m = OrganizationUser.objects.create(user=bob, org=acme, role=role_member)
    resp = client_as(admin_acme).delete(detail_url(m.id))
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not OrganizationUser.objects.filter(pk=m.id).exists()


@pytest.mark.django_db
def test_remove_self_403(client_as, admin_acme, acme):
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    resp = client_as(admin_acme).delete(detail_url(own.id))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_remove_last_admin_allowed_for_superadmin(
    client_as, superadmin, admin_acme, acme
):
    # No last-org-admin guard: superadmin can remove the only Org Admin.
    own = OrganizationUser.objects.get(user=admin_acme, org=acme)
    resp = client_as(superadmin).delete(detail_url(own.id))
    assert resp.status_code == status.HTTP_204_NO_CONTENT


# ---- assignable-target guards ----


@pytest.mark.django_db
def test_change_role_of_superadmin_400(
    client_as, admin_acme, acme, role_member, role_viewer, django_user_model
):
    sa = django_user_model.objects.create_user(
        email="sa-rerole@x.com", password="StrongPass123!", is_superadmin=True
    )
    membership = OrganizationUser.objects.create(user=sa, org=acme, role=role_member)
    resp = client_as(admin_acme).patch(
        detail_url(membership.id), {"role_id": role_viewer.id}, format="json"
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "superadmin_not_assignable"
    membership.refresh_from_db()
    assert membership.role_id == role_member.id


@pytest.mark.django_db
def test_change_role_denied_before_superadmin_reason(
    client_as, member_only, acme, role_member, role_viewer, django_user_model
):
    """A caller without MEMBERSHIPS.UPDATE gets permission_denied, not the
    superadmin reason — the guard must not disclose the target to someone
    who could not write anyway."""
    sa = django_user_model.objects.create_user(
        email="sa-hidden@x.com", password="StrongPass123!", is_superadmin=True
    )
    membership = OrganizationUser.objects.create(user=sa, org=acme, role=role_member)
    resp = client_as(member_only).patch(
        detail_url(membership.id), {"role_id": role_viewer.id}, format="json"
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_remove_superadmin_membership_allowed(
    client_as, admin_acme, acme, role_member, django_user_model
):
    """Removal converges toward the invariant and destroys no access."""
    sa = django_user_model.objects.create_user(
        email="sa-remove@x.com", password="StrongPass123!", is_superadmin=True
    )
    membership = OrganizationUser.objects.create(user=sa, org=acme, role=role_member)
    resp = client_as(admin_acme).delete(detail_url(membership.id))
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert not OrganizationUser.objects.filter(pk=membership.pk).exists()


# ---- visibility: a row the caller cannot see is 404, never 403 ----


@pytest.fixture
def admin_beta_member_acme(
    db, django_user_model, acme, beta, role_org_admin, role_member
):
    """Org Admin of beta (clears the MEMBERSHIPS door gate) and a plain Member
    of acme (no MEMBERSHIPS bits there)."""
    user = django_user_model.objects.create_user(
        email="admin-beta-member-acme-mem@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_patch_membership_without_bits_in_its_org_is_404(
    client_as, admin_beta_member_acme, acme, member_only, role_viewer
):
    row = OrganizationUser.objects.get(user=member_only, org=acme)

    resp = client_as(admin_beta_member_acme).patch(
        detail_url(row.id), {"role_id": role_viewer.id}, format="json"
    )

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "membership_not_found"
    row.refresh_from_db()
    assert row.role_id != role_viewer.id


@pytest.mark.django_db
def test_delete_membership_without_bits_in_its_org_is_404(
    client_as, admin_beta_member_acme, acme, member_only
):
    row = OrganizationUser.objects.get(user=member_only, org=acme)

    resp = client_as(admin_beta_member_acme).delete(detail_url(row.id))

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "membership_not_found"
    assert OrganizationUser.objects.filter(pk=row.id).exists()


# ---- the escalation ceiling on assignment ----
#
# Holding MEMBERSHIPS does not let you hand out authority you do not hold
# yourself. The rule never looks at `is_built_in`: Org Admin and an
# over-ceiling custom role are refused identically.


@pytest.fixture
def member_manager(db, django_user_model, acme, beta, role_org_admin):
    """A delegated admin of acme holding only the two admin resources, plus
    Org Admin of beta so the coarse door gate always passes."""
    role = Role.objects.create(name="Member Manager-mc", org=acme, is_built_in=False)
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
        email="member-manager-mc@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


@pytest.fixture
def acme_membership(db, member_only, acme):
    return OrganizationUser.objects.get(user=member_only, org=acme)


def _custom_role(acme, name, resource_type, permission):
    role = Role.objects.create(name=name, org=acme, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type=resource_type, permissions=int(permission))
    return role


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "new_role", "allowed"),
    [
        # Managing memberships must not let you mint an Org Admin whose powers you lack.
        ("member_manager", "org_admin", False),
        # Deliberate: Viewer grants workspace read bits this caller does not hold.
        ("member_manager", "viewer", False),
        # Not a built-in special case: an over-ceiling custom role is refused the same way.
        ("member_manager", "custom-flows-create", False),
        ("member_manager", "custom-memberships-read", True),
        # Equality is within the ceiling.
        ("admin_acme", "org_admin", True),
        # Viewer has a USE bit on flows that Org Admin lacks; only grantable bits are compared.
        ("admin_acme", "viewer", True),
        ("superadmin", "org_admin", True),
    ],
)
def test_role_assignment_is_capped_at_the_callers_own_authority(
    request, client_as, acme_membership, acme, role_member, role_org_admin, role_viewer, caller, new_role, allowed
):
    role = {
        "org_admin": role_org_admin,
        "viewer": role_viewer,
        "custom-flows-create": lambda: _custom_role(acme, "Flow Owner-mc", "flows", Permission.CREATE),
        "custom-memberships-read": lambda: _custom_role(acme, "Peer Manager-mc", "memberships", Permission.READ),
    }[new_role]
    role = role() if callable(role) else role

    resp = client_as(request.getfixturevalue(caller)).patch(
        detail_url(acme_membership.id), {"role_id": role.id}, format="json"
    )

    acme_membership.refresh_from_db()
    if allowed:
        assert resp.status_code == status.HTTP_200_OK
        assert acme_membership.role_id == role.id
    else:
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.json()["code"] == "permission_escalation_denied"
        assert acme_membership.role_id == role_member.id


@pytest.mark.django_db
def test_add_member_with_role_above_ceiling_is_403(
    client_as, member_manager, acme, role_org_admin, django_user_model
):
    newcomer = django_user_model.objects.create_user(email="newcomer-mc@example.com", password="StrongPass123!")

    resp = client_as(member_manager).post(
        LIST_URL, {"org_id": acme.id, "user_id": newcomer.id, "role_id": role_org_admin.id}, format="json"
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "permission_escalation_denied"
    assert not OrganizationUser.objects.filter(user=newcomer, org=acme).exists()


@pytest.mark.django_db
def test_missing_update_bit_is_permission_denied_not_escalation(
    client_as, django_user_model, acme, beta, acme_membership, role_org_admin
):
    """Ordering: the verb gate runs first, so a caller who may see the row but
    not write it is never told anything about the target role's power."""
    reader = Role.objects.create(name="Member Reader-mc", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=reader, resource_type="memberships", permissions=int(Permission.READ)
    )
    user = django_user_model.objects.create_user(
        email="member-reader-mc@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=acme, role=reader)

    resp = client_as(user).patch(
        detail_url(acme_membership.id), {"role_id": role_org_admin.id}, format="json"
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["code"] == "permission_denied"
