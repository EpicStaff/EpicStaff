import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import OrganizationUser

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
def test_list_bad_role_id_400(client_as, admin_acme):
    resp = client_as(admin_acme).get(LIST_URL + "?role_id=abc")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid"


@pytest.mark.django_db
def test_list_bad_status_400(client_as, admin_acme):
    resp = client_as(admin_acme).get(LIST_URL + "?status=Active")
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
def test_add_member_by_email(
    client_as, admin_acme, acme, role_member, django_user_model
):
    django_user_model.objects.create_user(email="new@x.com", password="StrongPass123!")
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "new@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["user"]["email"] == "new@x.com"


@pytest.mark.django_db
def test_add_member_by_user_id(
    client_as, admin_acme, acme, role_member, django_user_model
):
    target = django_user_model.objects.create_user(
        email="byid@x.com", password="StrongPass123!"
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "user_id": target.id, "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_add_unknown_email_404(client_as, admin_acme, acme, role_member):
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "nobody@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["code"] == "user_not_found"


@pytest.mark.django_db
def test_add_duplicate_400(client_as, admin_acme, acme, role_member, django_user_model):
    target = django_user_model.objects.create_user(
        email="dup@x.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=target, org=acme, role=role_member)
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "dup@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "membership_already_exists"


@pytest.mark.django_db
def test_add_to_org_caller_cannot_see_404(
    client_as, admin_acme, beta, role_member, django_user_model
):
    django_user_model.objects.create_user(email="x@x.com", password="StrongPass123!")
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": beta.id, "email": "x@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_add_missing_email_and_user_id_400(client_as, admin_acme, acme, role_member):
    resp = client_as(admin_acme).post(
        LIST_URL, {"org_id": acme.id, "role_id": role_member.id}, format="json"
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid"


@pytest.mark.django_db
def test_add_both_email_and_user_id_400(
    client_as, admin_acme, acme, role_member, django_user_model
):
    target = django_user_model.objects.create_user(
        email="both@x.com", password="StrongPass123!"
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {
            "org_id": acme.id,
            "email": "both@x.com",
            "user_id": target.id,
            "role_id": role_member.id,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_add_global_superadmin_role_400(client_as, admin_acme, acme, django_user_model):
    from tables.models.rbac_models import Role
    from tables.models.rbac_models.rbac_enums import BuiltInRole

    sa_role = Role.objects.get(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    )
    django_user_model.objects.create_user(
        email="sarole@x.com", password="StrongPass123!"
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "sarole@x.com", "role_id": sa_role.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "invalid_role_assignment"


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
def test_add_superadmin_by_email_400(
    client_as, admin_acme, acme, role_member, django_user_model
):
    django_user_model.objects.create_user(
        email="sa-target@x.com", password="StrongPass123!", is_superadmin=True
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "sa-target@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "superadmin_not_assignable"
    assert not OrganizationUser.objects.filter(
        user__email="sa-target@x.com", org=acme
    ).exists()


@pytest.mark.django_db
def test_add_superadmin_by_user_id_400(
    client_as, admin_acme, acme, role_member, django_user_model
):
    target = django_user_model.objects.create_user(
        email="sa-byid@x.com", password="StrongPass123!", is_superadmin=True
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "user_id": target.id, "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "superadmin_not_assignable"


@pytest.mark.django_db
def test_add_inactive_user_400(
    client_as, admin_acme, acme, role_member, django_user_model
):
    django_user_model.objects.create_user(
        email="off@x.com", password="StrongPass123!", is_active=False
    )
    resp = client_as(admin_acme).post(
        LIST_URL,
        {"org_id": acme.id, "email": "off@x.com", "role_id": role_member.id},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "user_not_active"


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
