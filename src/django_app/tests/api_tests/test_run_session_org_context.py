import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Run Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Run Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="run_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.mark.django_db
def test_run_session_rejects_other_orgs_flow(member_a, org_a, org_b):
    """A member of org A cannot run a flow owned by org B (403, before any
    session is published)."""
    graph_b = Graph.objects.create(name="B flow", org=org_b)
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))

    resp = client.post("/api/run-session/", {"graph_id": graph_b.id}, format="json")
    assert resp.status_code == 403
