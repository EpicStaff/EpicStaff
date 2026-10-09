import pytest
from django.test import override_settings
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import SubGraphNode
from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
    SubGraphNodeSerializer,
)

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def parent_graph(acme):
    return Graph.objects.create(name="subgraph-parent-flow", org=acme)


@pytest.fixture
def target_graph(acme):
    return Graph.objects.create(
        name="subgraph-target-flow", description="target description", org=acme
    )


@pytest.fixture
def subgraph_node(parent_graph, target_graph):
    return SubGraphNode.objects.create(
        graph=parent_graph, subgraph=target_graph, node_name="subgraph_node"
    )


def _serialize(subgraph_node_id):
    return SubGraphNodeSerializer(SubGraphNode.all_objects.get(pk=subgraph_node_id)).data


@pytest.mark.django_db
class TestSubGraphNodeSerializerSubgraphDetail:
    def test_subgraph_detail_is_populated_when_target_exists(self, subgraph_node, target_graph):
        data = _serialize(subgraph_node.id)

        assert data["subgraph"] == target_graph.id
        assert data["subgraph_detail"]["id"] == target_graph.id
        assert data["subgraph_detail"]["name"] == "subgraph-target-flow"
        assert data["subgraph_detail"]["description"] == "target description"

    @override_settings(SOFT_DELETE=False)
    def test_subgraph_detail_is_none_after_target_is_hard_deleted(
        self, subgraph_node, target_graph
    ):
        target_graph.delete()

        data = _serialize(subgraph_node.id)

        assert data["subgraph"] is None
        assert data["subgraph_detail"] is None

    @override_settings(SOFT_DELETE=True)
    def test_subgraph_detail_is_none_after_target_is_soft_deleted(
        self, subgraph_node, target_graph
    ):
        target_graph.delete()

        data = _serialize(subgraph_node.id)

        assert data["subgraph"] is None
        assert data["subgraph_detail"] is None

    def test_subgraph_node_endpoint_returns_none_detail_after_target_deleted(
        self, client_as, admin_acme, acme, subgraph_node, target_graph
    ):
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        target_graph.delete()

        response = client.get(f"/api/subgraph-nodes/{subgraph_node.id}/")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["subgraph_detail"] is None
