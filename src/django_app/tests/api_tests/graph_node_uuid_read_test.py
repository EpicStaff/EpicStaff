import pytest
from django.urls import reverse
from rest_framework import status

from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import create_node


@pytest.mark.django_db
def test_graph_detail_returns_uuid_on_every_node_list(auth_client, graph):
    nodes = {config.list_key: create_node(config.model_class, graph) for config in NODE_TYPE_REGISTRY}

    response = auth_client.get(reverse("graphs-detail", args=[graph.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    returned_uuids = {
        list_key: [item["uuid"] for item in response.data[list_key]] for list_key in nodes
    }
    assert returned_uuids == {list_key: [str(node.uuid)] for list_key, node in nodes.items()}
