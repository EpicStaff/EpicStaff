import pytest
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


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


@pytest.mark.django_db
def test_me_orgs_requires_auth():
    assert (
        APIClient().get("/api/permissions/me/orgs/").status_code
        == status.HTTP_401_UNAUTHORIZED
    )


@pytest.mark.django_db
def test_me_orgs_superadmin_star(auth_client, django_user_model):
    su = django_user_model.objects.create_superuser(
        email="su-meorgs@example.com", password="StrongPass123!"
    )
    body = auth_client(su).get("/api/permissions/me/orgs/").json()
    assert body["is_superadmin"] is True
    assert body["permissions"] == "*"


@pytest.mark.django_db
def test_me_orgs_lists_per_org_capabilities(
    auth_client, django_user_model, role_org_admin, role_member
):
    user = django_user_model.objects.create_user(
        email="multi-meorgs@example.com", password="StrongPass123!"
    )
    acme = Organization.objects.create(name="Acme")
    beta = Organization.objects.create(name="Beta")
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)

    body = auth_client(user).get("/api/permissions/me/orgs/").json()

    assert body["is_superadmin"] is False
    names = [o["org"]["name"] for o in body["orgs"]]
    assert names == ["Acme", "Beta"]
    acme_block = body["orgs"][0]
    assert acme_block["role"]["name"] == "Org Admin"
    assert set(acme_block["permissions"]["roles"]) == {
        "create",
        "read",
        "update",
        "delete",
    }
    assert body["orgs"][1]["permissions"]["roles"] == []  # Member has no roles perm
