"""Proves the catalog flip reaches the wire: `use` shows up under secrets for /me/ and /catalog/, and nowhere else."""

import pytest
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


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

    def test_catalog_lists_use_as_applicable_to_secrets_only(self, admin_client):
        catalog = admin_client.get("/api/permissions/catalog/").json()

        assert any(action["code"] == "use" for action in catalog["actions"])
        for entry in catalog["resource_types"]:
            if entry["code"] == "secrets":
                assert "use" in entry["applicable_actions"]
            else:
                assert "use" not in entry["applicable_actions"]
