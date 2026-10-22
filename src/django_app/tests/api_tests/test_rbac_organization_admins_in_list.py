"""Tests for the `admins` field embedded in GET /api/admin/organizations/."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

User = get_user_model()


# ---- fixtures ----


@pytest.fixture
def superadmin_jwt(superadmin_user):
    return str(RefreshToken.for_user(superadmin_user).access_token)


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


def _auth(client, jwt):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt}")
    return client


def _make_user(email, *, is_superadmin=False, is_active=True):
    return User.objects.create_user(
        email=email,
        password="UserPass123!",
        is_superadmin=is_superadmin,
        is_active=is_active,
    )


def _list_url():
    return "/api/admin/organizations/"


# ---- tests ----


@pytest.mark.django_db
def test_org_with_multiple_admins_returns_all_in_join_order(
    api_client, superadmin_jwt, org_admin_role
):
    org = Organization.objects.create(name="Acme")
    u1 = _make_user("a1@example.com")
    u2 = _make_user("a2@example.com")
    OrganizationUser.objects.create(user=u1, org=org, role=org_admin_role)
    OrganizationUser.objects.create(user=u2, org=org, role=org_admin_role)

    resp = _auth(api_client, superadmin_jwt).get(_list_url())
    assert resp.status_code == 200
    payload = next(o for o in resp.json()["results"] if o["id"] == org.id)
    assert [a["email"] for a in payload["admins"]] == [
        "a1@example.com",
        "a2@example.com",
    ]
    assert set(payload["admins"][0].keys()) == {
        "id",
        "email",
        "display_name",
        "avatar_url",
    }


@pytest.mark.django_db
def test_orgs_without_admins_show_the_oldest_active_superadmin(api_client, superadmin_jwt, superadmin_user):
    older_inactive = _make_user("old@example.com", is_superadmin=True, is_active=False)
    User.objects.filter(pk=older_inactive.pk).update(created_at=superadmin_user.created_at)
    Organization.objects.create(name="OrgX")
    Organization.objects.create(name="OrgY")

    resp = _auth(api_client, superadmin_jwt).get(_list_url())

    targets = [org for org in resp.json()["results"] if org["name"] in ("OrgX", "OrgY")]
    assert [[admin["id"] for admin in org["admins"]] for org in targets] == [[superadmin_user.id]] * 2


@pytest.mark.django_db
def test_avatar_url_is_the_avatar_endpoint_when_set_and_null_when_unset(
    api_client, superadmin_jwt, org_admin_role
):
    org = Organization.objects.create(name="AvatarOrg")
    u_no = _make_user("noava@example.com")
    u_yes = _make_user("ava@example.com")
    OrganizationUser.objects.create(user=u_no, org=org, role=org_admin_role)
    OrganizationUser.objects.create(user=u_yes, org=org, role=org_admin_role)
    u_yes.avatar.name = f"avatars/{u_yes.id}/6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a.png"
    u_yes.save(update_fields=["avatar"])

    resp = _auth(api_client, superadmin_jwt).get(_list_url())

    payload = next(o for o in resp.json()["results"] if o["id"] == org.id)
    by_email = {a["email"]: a for a in payload["admins"]}
    assert by_email["noava@example.com"]["avatar_url"] is None
    assert by_email["ava@example.com"]["avatar_url"] == (
        f"/api/users/{u_yes.id}/avatar/?v=6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a"
    )


@pytest.mark.django_db
def test_single_org_endpoints_do_not_include_admins(api_client, superadmin_jwt):
    org = Organization.objects.create(name="ToRename")

    resp = _auth(api_client, superadmin_jwt).patch(
        f"/api/admin/organizations/{org.id}/",
        {"name": "Renamed"},
        format="json",
    )
    assert resp.status_code == 200
    assert "admins" not in resp.json()

    resp = _auth(api_client, superadmin_jwt).post(
        _list_url(), {"name": "Brand New"}, format="json"
    )
    assert resp.status_code == 201
    assert "admins" not in resp.json()
