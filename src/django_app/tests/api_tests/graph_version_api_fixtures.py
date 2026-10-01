"""Shared fixtures for the graph-version API tests (secret declarations, preview).

Star-imported by those modules — mirrors the `from tests.rbac_cross_org_fixtures import *`
pattern. Builds its own APIClient rather than using the shared `auth_client` fixture:
under tests/settings.py that fixture is inert and every request 403s.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models import PythonCode, PythonNode
from tables.models.graph_models import Graph
from tables.services.secrets import secret_service

SECRET_READING_CODE = 'def main(**kwargs):\n    return get_secret("STRIPE_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org VersionSecrets")


@pytest.fixture
def client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_versionsecrets@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return api_client


@pytest.fixture
def graph_with_declared_secret(org):
    """A flow whose Python node reads STRIPE_KEY and is declared to do so."""
    graph = Graph.objects.create(name="flow-with-secret", org=org)
    secret = secret_service.create(text="sk-live-x", org=org, name="STRIPE_KEY")
    python_code = PythonCode.objects.create(code=SECRET_READING_CODE)
    python_code.secrets.set([secret])
    PythonNode.objects.create(
        graph=graph, node_name="Python-Node #1", python_code=python_code
    )
    return graph, secret


def save_version(*, client, graph, name="with-secret"):
    response = client.post(
        reverse("graph-versions-list"),
        {"graph_id": graph.id, "name": name},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.content
    return response.data["id"]
