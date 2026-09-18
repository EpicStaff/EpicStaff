"""Secret declarations survive a version restore over HTTP, warnings included.

tests/graph_versioning_tests/test_secret_declarations.py covers the mechanism at the
service layer. This file covers the seam above it: that the view passes the snapshot's
declarations through, and that a declaration which could not be re-linked reaches the
caller in the response's existing `warnings` list rather than vanishing.

Builds its own APIClient rather than using the shared `auth_client` fixture: under
tests/settings.py that fixture is inert and every request 403s, so the whole of
tests/api_tests/test_graph_versioning.py currently fails for reasons unrelated to
secrets. Follows tests/api_tests/test_secret_selection_cross_org.py instead.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import PythonCode, PythonNode
from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service
from tables.services.secrets.declaration_validator import SecretDeclarationValidator

CODE = 'def main(**kwargs):\n    return get_secret("STRIPE_KEY")\n'


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
    python_code = PythonCode.objects.create(code=CODE)
    python_code.secrets.set([secret])
    PythonNode.objects.create(
        graph=graph, node_name="Python-Node #1", python_code=python_code
    )
    return graph, secret


def _save_version(*, client, graph, name="with-secret"):
    response = client.post(
        reverse("graph-versions-list"),
        {"graph_id": graph.id, "name": name},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.content
    return response.data["id"]


def _restore(*, client, graph, version_id):
    graph.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version_id]),
        {"save_version": graph.save_version},
        format="json",
    )


def _declared_names(*, graph):
    node = PythonNode.objects.filter(graph=graph).select_related("python_code").get()
    return sorted(node.python_code.secrets.values_list("name", flat=True))


@pytest.mark.django_db
def test_restore_reattaches_the_declaration_and_leaves_the_flow_runnable(
    client, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version_id = _save_version(client=client, graph=graph)

    response = _restore(client=client, graph=graph, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["warnings"] == []
    assert _declared_names(graph=graph) == ["STRIPE_KEY"]
    assert SecretDeclarationValidator().violations(graph_id=graph.pk) == []


@pytest.mark.django_db
def test_restore_reports_a_dropped_declaration_in_the_response_warnings(
    client, graph_with_declared_secret
):
    """A secret deleted between save and restore must be reported, not silently
    dropped — the caller has no other way to learn the flow is now unrunnable."""
    graph, secret = graph_with_declared_secret
    version_id = _save_version(client=client, graph=graph)
    secret.delete()

    response = _restore(client=client, graph=graph, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [w["type"] for w in response.data["warnings"]] == [
        "secret_declaration_dropped"
    ]
    assert "STRIPE_KEY" in response.data["warnings"][0]["reason"]
    assert _declared_names(graph=graph) == []


@pytest.mark.django_db
def test_create_graph_from_a_version_keeps_the_declaration(
    client, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version_id = _save_version(client=client, graph=graph)

    response = client.post(
        reverse("graph-versions-create-graph", args=[version_id]), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(pk=response.data["graph_id"])
    assert new_graph.pk != graph.pk
    assert _declared_names(graph=new_graph) == ["STRIPE_KEY"]


@pytest.mark.django_db
def test_the_snapshot_is_never_exposed_by_the_read_endpoints(
    client, graph_with_declared_secret
):
    """The declarations block lives in a JSONField the serializer does not expose.
    It holds only names, never values, but it is still an authorisation record —
    and the code in the same snapshot is user source. Neither belongs in a list or
    detail payload."""
    graph, _ = graph_with_declared_secret
    version_id = _save_version(client=client, graph=graph)

    detail = client.get(reverse("graph-versions-detail", args=[version_id]))
    listed = client.get(reverse("graph-versions-list"))

    # Both statuses asserted: a 403 body contains none of the forbidden strings
    # either, so without this the test would pass for entirely the wrong reason.
    assert detail.status_code == status.HTTP_200_OK, detail.content
    assert listed.status_code == status.HTTP_200_OK, listed.content
    for payload in (detail.data, listed.data):
        body = str(payload)
        assert "secret_declarations" not in body
        assert "snapshot" not in body
        assert "STRIPE_KEY" not in body
