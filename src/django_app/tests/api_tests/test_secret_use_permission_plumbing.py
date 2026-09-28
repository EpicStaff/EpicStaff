"""Proves the catalog flip reaches the wire: `use` shows up under secrets for /me/, and under exactly the use-enforced resources for /catalog/."""

import pytest
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole, ResourceType

# Resources where `use` is actually enforced (see
# tests/services_tests/test_builtin_role_permissions.py::USE_ENFORCED_RESOURCES
# for the authoritative definition and rationale). Duplicated here rather than
# imported to avoid a test-to-test import.
USE_ENFORCED_RESOURCES = {ResourceType.SECRETS.value}


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Use Plumbing")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="use_plumbing_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
class TestUseIsReportedToTheFrontend:
    def test_permissions_me_reports_use_for_an_org_admin(self, admin_client):
        response = admin_client.get("/api/permissions/me/")

        assert response.status_code == 200
        assert "use" in response.json()["permissions"]["secrets"]

    def test_permissions_me_reports_crud_without_use_on_persistent_data(self, admin_client):
        response = admin_client.get("/api/permissions/me/")

        assert response.status_code == 200
        assert response.json()["permissions"]["persistent_data"] == [
            "create",
            "read",
            "update",
            "delete",
        ]

    def test_catalog_lists_use_only_for_use_enforced_resources(self, admin_client):
        catalog = admin_client.get("/api/permissions/catalog/").json()

        assert any(action["code"] == "use" for action in catalog["actions"])
        resources_with_use = {
            entry["code"]
            for entry in catalog["resource_types"]
            if "use" in entry["applicable_actions"]
        }
        assert resources_with_use == USE_ENFORCED_RESOURCES
