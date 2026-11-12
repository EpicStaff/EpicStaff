"""Graph RAG visualization and detail proxy endpoints.

The endpoints proxy to knowledge_new; the knowledge client is the only thing
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
ENTITY_DETAIL_URL = "/api/graph-rag/{pk}/entity/{entity_id}/"
RELATIONSHIP_DETAIL_URL = "/api/graph-rag/{pk}/relationship/{relationship_id}/"

_GRAPH_RAG_VIZ_CLIENT = "tables.clients.knowledge.KnowledgeClient.get_visualization"
_GRAPH_RAG_ENTITY_CLIENT = "tables.clients.knowledge.KnowledgeClient.get_entity_detail"
_GRAPH_RAG_REL_CLIENT = "tables.clients.knowledge.KnowledgeClient.get_relationship_detail"

SAMPLE_RESPONSE = {
    "entities": [
        {"id": "e1", "title": "Entity 1", "type": "organization", "degree": 5, "community_ids": []},
        {"id": "e2", "title": "Entity 2", "type": "person", "degree": 3, "community_ids": []},
    ],
    "relationships": [
        {"id": "r1", "source": "e1", "target": "e2", "weight": 1.0},
    ],
    "total_entities": 2,
    "total_relationships": 1,
}


def _make_graph_rag(org):
    collection = SourceCollection.objects.create(collection_name="vis-col", org=org)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(base_rag_type=base_rag)


# -- Visualization: Happy path --


def test_visualization_returns_upstream_data(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == SAMPLE_RESPONSE
    mock_viz.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, max_entities=None, search=None
    )


def test_visualization_passes_max_entities(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url, {"max_entities": "200"})

    assert response.status_code == status.HTTP_200_OK
    mock_viz.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, max_entities=200, search=None
    )


def test_visualization_passes_search(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url, {"search": "Entity"})

    assert response.status_code == status.HTTP_200_OK
    mock_viz.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, max_entities=None, search="Entity"
    )


def test_visualization_passes_search_and_max_entities(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    with patch(_GRAPH_RAG_VIZ_CLIENT, return_value=SAMPLE_RESPONSE) as mock_viz:
        response = auth_client.get(url, {"max_entities": "100", "search": "test"})

    assert response.status_code == status.HTTP_200_OK
    mock_viz.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, max_entities=100, search="test"
    )


# -- Visualization: Validation --


def test_visualization_invalid_max_entities_returns_400(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    response = auth_client.get(url, {"max_entities": "abc"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "max_entities" in response.data["error"]


# -- Visualization: Upstream errors --


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


# -- Visualization: Org scoping --


def test_visualization_cross_org_returns_404(auth_client):
    """A graph RAG belonging to another org must not be accessible."""
    from rbac.models import Organization

    other_org = Organization.objects.create(name="Other Org")
    graph_rag = _make_graph_rag(other_org)
    url = VISUALIZATION_URL.format(pk=graph_rag.graph_rag_id)

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


# -- Entity detail: Happy path --


def test_entity_detail_returns_upstream_data(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = ENTITY_DETAIL_URL.format(pk=graph_rag.graph_rag_id, entity_id="e1")

    upstream = {"description": "A large corporation."}
    with patch(_GRAPH_RAG_ENTITY_CLIENT, return_value=upstream) as mock_entity:
        response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == upstream
    mock_entity.assert_called_once_with(rag_id=graph_rag.graph_rag_id, entity_id="e1")


# -- Entity detail: Upstream errors --


@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (ClientResourceNotFoundError("not found"), status.HTTP_404_NOT_FOUND),
        (ClientBadGatewayError("knowledge_new is down"), status.HTTP_502_BAD_GATEWAY),
        (ClientTimeoutError("timed out"), status.HTTP_504_GATEWAY_TIMEOUT),
    ],
    ids=["upstream-404", "upstream-502", "upstream-timeout"],
)
def test_entity_detail_maps_upstream_errors(
    auth_client, default_org, upstream_error, expected_status
):
    graph_rag = _make_graph_rag(default_org)
    url = ENTITY_DETAIL_URL.format(pk=graph_rag.graph_rag_id, entity_id="e1")

    with patch(_GRAPH_RAG_ENTITY_CLIENT, side_effect=upstream_error):
        response = auth_client.get(url)

    assert response.status_code == expected_status
    assert "error" in response.data


# -- Entity detail: Org scoping --


def test_entity_detail_cross_org_returns_404(auth_client):
    from rbac.models import Organization

    other_org = Organization.objects.create(name="Other Org")
    graph_rag = _make_graph_rag(other_org)
    url = ENTITY_DETAIL_URL.format(pk=graph_rag.graph_rag_id, entity_id="e1")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


# -- Relationship detail: Happy path --


def test_relationship_detail_returns_upstream_data(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)
    url = RELATIONSHIP_DETAIL_URL.format(pk=graph_rag.graph_rag_id, relationship_id="r1")

    upstream = {"description": "Works at the company."}
    with patch(_GRAPH_RAG_REL_CLIENT, return_value=upstream) as mock_rel:
        response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == upstream
    mock_rel.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, relationship_id="r1"
    )


# -- Relationship detail: Upstream errors --


@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (ClientResourceNotFoundError("not found"), status.HTTP_404_NOT_FOUND),
        (ClientBadGatewayError("knowledge_new is down"), status.HTTP_502_BAD_GATEWAY),
        (ClientTimeoutError("timed out"), status.HTTP_504_GATEWAY_TIMEOUT),
    ],
    ids=["upstream-404", "upstream-502", "upstream-timeout"],
)
def test_relationship_detail_maps_upstream_errors(
    auth_client, default_org, upstream_error, expected_status
):
    graph_rag = _make_graph_rag(default_org)
    url = RELATIONSHIP_DETAIL_URL.format(pk=graph_rag.graph_rag_id, relationship_id="r1")

    with patch(_GRAPH_RAG_REL_CLIENT, side_effect=upstream_error):
        response = auth_client.get(url)

    assert response.status_code == expected_status
    assert "error" in response.data


# -- Relationship detail: Org scoping --


def test_relationship_detail_cross_org_returns_404(auth_client):
    from rbac.models import Organization

    other_org = Organization.objects.create(name="Other Org")
    graph_rag = _make_graph_rag(other_org)
    url = RELATIONSHIP_DETAIL_URL.format(pk=graph_rag.graph_rag_id, relationship_id="r1")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND
