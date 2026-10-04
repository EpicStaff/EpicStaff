"""A caller who can delete sessions in one org and only run flows in another
must not be able to link a session of the second org under a session of the
first, because deleting the parent cascades to its sub-sessions."""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import OrganizationUser
from tables.models import Edge, Graph, PythonCode, PythonNode, Session, StartNode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _build_runnable_graph(name: str, org) -> Graph:
    graph = Graph.objects.create(name=name, org=org)
    start_node = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(code="def main():\n    return 1\n")
    python_node = PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="python_node"
    )
    Edge.objects.create(
        graph=graph, start_node_id=start_node.pk, end_node_id=python_node.pk
    )
    return graph


@pytest.fixture
def acme_admin_with_beta_viewer(admin_acme, beta, role_viewer):
    """Org Admin (FLOWS DELETE) in Acme, Viewer (FLOWS READ only) in Beta."""
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_viewer)
    return admin_acme


@pytest.fixture
def acme_session(acme):
    graph = Graph.objects.create(name="acme parent flow", org=acme)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.END)


@pytest.fixture
def beta_graph(beta):
    return _build_runnable_graph("beta child flow", beta)


@pytest.mark.django_db
def test_cannot_link_other_org_run_under_own_org_session(
    client_as, acme_admin_with_beta_viewer, beta, beta_graph, acme_session, redis_client_mock
):
    client = client_as(acme_admin_with_beta_viewer)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = client.post(
        reverse("run-session"),
        {"graph_id": beta_graph.pk, "variables": {}, "parent_session_id": acme_session.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert not Session.objects.filter(graph=beta_graph).exists()


@pytest.mark.django_db
def test_deleting_own_org_session_never_deletes_other_org_session(
    client_as,
    acme_admin_with_beta_viewer,
    acme,
    beta,
    beta_graph,
    acme_session,
    redis_client_mock,
):
    client = client_as(acme_admin_with_beta_viewer)
    beta_session = Session.objects.create(
        graph=beta_graph, status=Session.SessionStatus.END
    )
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))
    client.post(
        reverse("run-session"),
        {"graph_id": beta_graph.pk, "variables": {}, "parent_session_id": acme_session.pk},
        format="json",
    )
    beta_session_ids = set(
        Session.objects.filter(graph=beta_graph).values_list("id", flat=True)
    )

    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    delete_response = client.delete(f"/api/sessions/{acme_session.pk}/")

    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    assert beta_session.id in Session.objects.values_list("id", flat=True)
    assert set(
        Session.objects.filter(graph=beta_graph).values_list("id", flat=True)
    ) == beta_session_ids
