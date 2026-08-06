"""Bulk-save (graphs-save-flow) coverage for KnowledgeNode search_configs.

The bulk path must accept the same nested `search_configs` wrapper the CRUD
endpoint does; a regression here silently dropped it and stored search_configs
as null.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import KnowledgeNode
from tables.models.knowledge_models import (
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeNaiveRagSearchConfig,
)
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    # tests settings clear auth classes, so a Bearer token never resolves to a
    # user and HasOrgPermission 403s — force_authenticate + active-org header is
    # the working pattern for org-scoped endpoints here.
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


@pytest.mark.django_db
def test_create_knowledge_node_with_naive_search_config(auth_client, graph):
    """Nested search_configs.naive must persist as a naive config row."""
    payload = {
        "save_version": graph.save_version,
        "knowledge_node_list": [
            {
                "graph": graph.id,
                "node_name": "KB Retriever",
                "search_configs": {
                    "naive": {"search_limit": 3, "similarity_threshold": 0.2}
                },
            }
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    node = KnowledgeNode.objects.get(graph=graph, node_name="KB Retriever")
    cfg = KnowledgeNodeNaiveRagSearchConfig.objects.get(knowledge_node=node)
    assert cfg.search_limit == 3
    assert float(cfg.similarity_threshold) == 0.2


@pytest.mark.django_db
def test_create_knowledge_node_with_graph_basic_search_config(auth_client, graph):
    """Nested search_configs.graph routes search_method onto the node and its
    basic params onto the basic config row."""
    payload = {
        "save_version": graph.save_version,
        "knowledge_node_list": [
            {
                "graph": graph.id,
                "node_name": "KB Graph",
                "search_configs": {
                    "graph": {
                        "search_method": "basic",
                        "basic": {"k": 8, "max_context_tokens": 8000},
                    }
                },
            }
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    node = KnowledgeNode.objects.get(graph=graph, node_name="KB Graph")
    assert node.search_method == "basic"
    assert (
        KnowledgeNodeGraphRagBasicSearchConfig.objects.get(knowledge_node=node).k == 8
    )


@pytest.mark.django_db
def test_update_knowledge_node_without_search_configs_keeps_existing(
    auth_client, graph
):
    """Omitting search_configs on update must leave the stored row untouched."""
    node = KnowledgeNode.objects.create(graph=graph, node_name="KB Keep")
    KnowledgeNodeNaiveRagSearchConfig.objects.create(
        knowledge_node=node, search_limit=9
    )

    payload = {
        "save_version": graph.save_version,
        "knowledge_node_list": [
            {"id": node.id, "graph": graph.id, "node_name": "KB Keep Renamed"},
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert (
        KnowledgeNodeNaiveRagSearchConfig.objects.get(knowledge_node=node).search_limit
        == 9
    )
