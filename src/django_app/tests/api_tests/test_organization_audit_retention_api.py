import pytest
from rest_framework import status

from rbac.models import (
    Organization,
    OrganizationConfig,
    OrganizationUser,
    Role,
    RolePermission,
)
from rbac.models.enums import Permission

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = "/api/admin/organizations/"


def detail_url(org_id):
    return f"/api/admin/organizations/{org_id}/"


def retention_of(org):
    return OrganizationConfig.objects.get(org=org).audit_retention_days


@pytest.fixture(autouse=True)
def _no_storage_provisioning(mocker):
    # MinIO is an external service; org creation calls it.
    mocker.patch(
        "rbac.governance.organizations.org_storage_provisioning_service.provision_for_organization"
    )


@pytest.fixture
def admin_of_acme_and_beta(db, django_user_model, acme, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-acme-beta-retention@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


# ---- create ----


@pytest.mark.django_db
def test_superadmin_creates_org_with_retention(client_as, superadmin):
    response = client_as(superadmin).post(
        LIST_URL, {"name": "Retained Co", "audit_retention_days": 90}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["config"]["audit_retention_days"] == 90
    assert retention_of(Organization.objects.get(name="Retained Co")) == 90


@pytest.mark.django_db
def test_create_without_retention_defaults_to_unlimited(client_as, superadmin):
    response = client_as(superadmin).post(LIST_URL, {"name": "Default Co"}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["config"]["audit_retention_days"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("days", [-1, 36501, "abc", True, None])
def test_create_rejects_invalid_retention(client_as, superadmin, days):
    response = client_as(superadmin).post(
        LIST_URL, {"name": "Invalid Co", "audit_retention_days": days}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Organization.objects.filter(name="Invalid Co").exists()


# ---- partial_update ----


@pytest.mark.django_db
def test_patch_with_only_retention_updates_url_org_not_active_org(
    client_as, admin_of_acme_and_beta, acme, beta
):
    client = client_as(admin_of_acme_and_beta)

    response = client.patch(
        detail_url(beta.id),
        {"audit_retention_days": 30},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(acme.id),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == beta.id
    assert response.json()["config"]["audit_retention_days"] == 30
    assert retention_of(beta) == 30
    assert not OrganizationConfig.objects.filter(org=acme, audit_retention_days=30).exists()


@pytest.mark.django_db
def test_patch_with_name_and_retention_updates_both(client_as, admin_acme, acme):
    response = client_as(admin_acme).patch(
        detail_url(acme.id), {"name": "Acme Renamed", "audit_retention_days": 36500}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "Acme Renamed"
    assert response.json()["config"]["audit_retention_days"] == 36500


@pytest.mark.django_db
def test_patch_with_empty_body_still_requires_name(client_as, admin_acme, acme):
    response = client_as(admin_acme).patch(detail_url(acme.id), {}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_cross_org_retention_patch_is_404_and_leaves_value(client_as, admin_acme, beta):
    OrganizationConfig.objects.create(org=beta, audit_retention_days=7)

    response = client_as(admin_acme).patch(
        detail_url(beta.id), {"audit_retention_days": 1}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "organization_not_found"
    assert retention_of(beta) == 7


@pytest.mark.django_db
def test_retention_patch_with_read_but_no_update_is_403_and_leaves_value(
    client_as, django_user_model, acme, beta, role_org_admin
):
    # Org Admin of beta passes the door gate; the 403 comes from the per-org check on acme.
    reader_role = Role.objects.create(name="OrgReaderOnly-retention", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=reader_role, resource_type="organizations", permissions=int(Permission.READ)
    )
    reader = django_user_model.objects.create_user(
        email="org-reader-retention@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=reader, org=beta, role=role_org_admin)
    OrganizationUser.objects.create(user=reader, org=acme, role=reader_role)
    OrganizationConfig.objects.create(org=acme, audit_retention_days=7)

    response = client_as(reader).patch(
        detail_url(acme.id),
        {"audit_retention_days": 1},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(beta.id),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["code"] == "permission_denied"
    assert retention_of(acme) == 7


@pytest.mark.django_db
@pytest.mark.parametrize("days", [-1, 36501, "abc", True, None])
def test_patch_rejects_invalid_retention(client_as, admin_acme, acme, days):
    OrganizationConfig.objects.create(org=acme, audit_retention_days=7)

    response = client_as(admin_acme).patch(
        detail_url(acme.id), {"audit_retention_days": days}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert retention_of(acme) == 7
