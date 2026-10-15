import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from rbac.models import OrganizationUser
from tables.models import Graph
from tables.models.graph_models import SubGraphNode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    """Org Admin (built-in) of Beta only."""
    user = django_user_model.objects.create_user(
        email="admin-beta-subflow@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def target_graph(acme):
    """The graph whose subflow-usage we query."""
    return Graph.objects.create(name="target-flow", org=acme)


@pytest.fixture
def parent_graph_a(acme):
    return Graph.objects.create(name="parent-a", org=acme)


@pytest.fixture
def parent_graph_b(acme):
    return Graph.objects.create(name="parent-b", org=acme)


def _url(graph_id):
    return reverse("graphs-subflow-usage", args=[graph_id])


@pytest.mark.django_db
class TestSubflowUsage:
    def test_no_references(self, client_as, admin_acme, acme, target_graph):
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"parent_flow_ids": []}

    def test_single_parent(
        self, client_as, admin_acme, acme, target_graph, parent_graph_a
    ):
        SubGraphNode.all_objects.create(graph=parent_graph_a, subgraph=target_graph)
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["parent_flow_ids"] == [parent_graph_a.id]

    def test_multiple_parents(
        self,
        client_as,
        admin_acme,
        acme,
        target_graph,
        parent_graph_a,
        parent_graph_b,
    ):
        SubGraphNode.all_objects.create(graph=parent_graph_a, subgraph=target_graph)
        SubGraphNode.all_objects.create(graph=parent_graph_b, subgraph=target_graph)
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data["parent_flow_ids"]) == {
            parent_graph_a.id,
            parent_graph_b.id,
        }

    def test_deduplicates_same_parent(
        self, client_as, admin_acme, acme, target_graph, parent_graph_a
    ):
        """Two SubGraphNodes in the same parent flow both reference the target.
        The result should contain only one entry (distinct parent flows)."""
        SubGraphNode.all_objects.create(graph=parent_graph_a, subgraph=target_graph)
        SubGraphNode.all_objects.create(graph=parent_graph_a, subgraph=target_graph)
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["parent_flow_ids"] == [parent_graph_a.id]

    def test_soft_deleted_excluded(
        self, client_as, admin_acme, acme, target_graph, parent_graph_a
    ):
        """A soft-deleted SubGraphNode should not be included."""
        SubGraphNode.all_objects.create(
            graph=parent_graph_a,
            subgraph=target_graph,
            active=False,
            soft_deleted_at=timezone.now(),
        )
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"parent_flow_ids": []}

    def test_cross_org_returns_404(
        self, client_as, admin_beta, beta, target_graph
    ):
        """A user in beta org cannot see a graph owned by acme."""
        client = client_as(admin_beta)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

        response = client.get(_url(target_graph.id))

        assert response.status_code == status.HTTP_404_NOT_FOUND
