"""Graph RAG visualization proxy endpoint.

The endpoint proxies to knowledge_new; the knowledge client is the only thing
replaced because it is the HTTP boundary to the upstream service.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from tables.clients.errors import (
    ClientBadGatewayError,
    ClientResourceNotFoundError,
    ClientTimeoutError,
)
from tables.models.knowledge_models import BaseRagType, GraphRag, SourceCollection

pytestmark = pytest.mark.django_db

VISUALIZATION_URL = "/api/graph-rag/{pk}/visualization/"
_GRAPH_RAG_VIZ_CLIENT = "tables.clients.knowledge.KnowledgeClient.get_visualization"

SAMPLE_RESPONSE = {
    "entities": [
        {"id": "e1", "name": "Entity 1", "type": "organization"},
        {"id": "e2", "name": "Entity 2", "type": "person"},
    ],
    "relationships": [
        {"source": "e1", "target": "e2", "type": "works_for"},
    ],
}


def _make_graph_rag(org):
    collection = SourceCollection.objects.create(collection_name="vis-col", org=org)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(base_rag_type=base_rag)


# -- Happy path --


def test_visualization_returns_upstream_data(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == SAMPLE_RESPONSE
    mock_viz.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=None)


def test_visualization_passes_max_entities(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url, {"max_entities": "200"})

    assert response.status_code == status.HTTP_200_OK
    mock_viz.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=200)


# -- Validation --


def test_visualization_invalid_max_entities_returns_400(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    response = auth_client.get(url, {"max_entities": "abc"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "max_entities" in response.data["error"]


# -- Upstream errors --


@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (ClientResourceNotFoundError("not found"), status.HTTP_404_NOT_FOUND),
        (ClientBadGatewayError("knowledge_new is down"), status.HTTP_502_BAD_GATEWAY),
        (ClientTimeoutError("timed out"), status.HTTP_504_GATEWAY_TIMEOUT),
    ],
    ids=["upstream-404", "upstream-502", "upstream-timeout"],
)
def test_visualization_maps_upstream_errors(
    auth_client, default_org, upstream_error, expected_status
):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, side_effect=upstream_error):
        response = auth_client.get(url)

    assert response.status_code == expected_status
    assert "error" in response.data


# -- Org scoping --


def test_visualization_cross_org_returns_404(auth_client):
    """A graph RAG belonging to another org must not be accessible."""
    from rbac.models import Organization

    other_org = Organization.objects.create(name="Other Org")
    graph_rag = _make_graph_rag(other_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND
