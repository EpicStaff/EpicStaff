import pytest
from rest_framework.test import APIClient

from agents.models.surface_models import Surface
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org")


def _client(django_user_model, org, role_name, email):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
def test_viewer_cannot_create_surface(db, django_user_model, org):
    client = _client(django_user_model, org, BuiltInRole.VIEWER, "v@example.com")
    resp = client.post("/api/surfaces/", {"name": "s"}, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_viewer_can_read_surface(db, django_user_model, org):
    Surface.objects.create(name="s", organization=org)
    client = _client(django_user_model, org, BuiltInRole.VIEWER, "v2@example.com")
    resp = client.get("/api/surfaces/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_member_can_create_surface(db, django_user_model, org):
    client = _client(django_user_model, org, BuiltInRole.MEMBER, "m@example.com")
    resp = client.post("/api/surfaces/", {"name": "s"}, format="json")
    assert resp.status_code == 201


@pytest.mark.django_db
def test_no_membership_forbidden(db, django_user_model, org):
    user = django_user_model.objects.create_user(
        email="none@example.com", password="StrongPass123!"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    resp = client.get("/api/surfaces/")
    assert resp.status_code == 403
