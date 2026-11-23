"""Graph RAG index read endpoints: visualization, entity/relationship detail, table data, table summary.

The endpoints proxy to knowledge_new; the knowledge client is the only thing
replaced because it is the HTTP boundary to the upstream service. Errors reach the
browser through the global exception handler as `{type, errors: [{code, detail, attr, context}]}`.
"""

from functools import partial
from unittest.mock import patch

import httpx
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models.enums import Permission, ResourceType
from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientResourceNotFoundError,
    ClientTimeoutError,
    KnowledgeGraphNotIndexedError,
)
from tables.clients.knowledge import KnowledgeClient
from tables.models.knowledge_models import BaseRagType, GraphRag, SourceCollection
from tests.rbac_cross_org_fixtures import beta, custom_role_user  # noqa: F401

pytestmark = pytest.mark.django_db

VISUALIZATION_URL = "/api/graph-rag/{pk}/visualization/"
ENTITY_DETAIL_URL = "/api/graph-rag/{pk}/entity/{entity_id}/"
RELATIONSHIP_DETAIL_URL = "/api/graph-rag/{pk}/relationship/{relationship_id}/"
TABLE_SUMMARY_URL = "/api/graph-rag/{pk}/table-summary/"
TABLE_DATA_URL = "/api/graph-rag/{pk}/tables/{table_name}/"

_CLIENT = "tables.clients.knowledge.KnowledgeClient"
_VISUALIZATION_CLIENT = f"{_CLIENT}.get_visualization"
_ENTITY_CLIENT = f"{_CLIENT}.get_entity_detail"
_RELATIONSHIP_CLIENT = f"{_CLIENT}.get_relationship_detail"
_TABLE_SUMMARY_CLIENT = f"{_CLIENT}.get_table_summary"
_TABLE_DATA_CLIENT = f"{_CLIENT}.get_table_data"

SAMPLE_VISUALIZATION = {
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
SAMPLE_TABLE_SUMMARY = {
    "tables": [
        {"name": "entities", "label": "Entities", "count": 2},
        {"name": "relationships", "label": "Relationships", "count": 1},
    ]
}
SAMPLE_TABLE_DATA = {
    "columns": ["id", "title"],
    "rows": [{"id": "e1", "title": "Entity 1"}],
    "total": 1,
    "page": 1,
    "page_size": 10,
}

# Every endpoint as (url template kwargs, client method patched, sample upstream body).
_ENDPOINTS = {
    "visualization": (VISUALIZATION_URL, {}, _VISUALIZATION_CLIENT, SAMPLE_VISUALIZATION),
    "entity-detail": (ENTITY_DETAIL_URL, {"entity_id": "e1"}, _ENTITY_CLIENT, {"description": "d"}),
    "relationship-detail": (
        RELATIONSHIP_DETAIL_URL,
        {"relationship_id": "r1"},
        _RELATIONSHIP_CLIENT,
        {"description": "d"},
    ),
    "table-summary": (TABLE_SUMMARY_URL, {}, _TABLE_SUMMARY_CLIENT, SAMPLE_TABLE_SUMMARY),
    "table-data": (TABLE_DATA_URL, {"table_name": "entities"}, _TABLE_DATA_CLIENT, SAMPLE_TABLE_DATA),
}
_ENDPOINT_NAMES = list(_ENDPOINTS)

# The knowledge_new path each endpoint is proxied to.
_UPSTREAM_PATHS = {
    "visualization": "/rags/graph/{rag_id}/visualization/",
    "entity-detail": "/rags/graph/{rag_id}/entity/e1/",
    "relationship-detail": "/rags/graph/{rag_id}/relationship/r1/",
    "table-summary": "/rags/graph/{rag_id}/table-summary/",
    "table-data": "/rags/graph/{rag_id}/tables/entities/",
}
_VIEW_KNOWLEDGE_CLIENT = "tables.views.knowledge_views.graph_rag_views.KnowledgeClient"


def _make_graph_rag(org):
    collection = SourceCollection.objects.create(collection_name="vis-col", org=org)
    base_rag = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    return GraphRag.objects.create(base_rag_type=base_rag)


def _endpoint_url(endpoint_name: str, graph_rag: GraphRag) -> str:
    url_template, url_kwargs, _, _ = _ENDPOINTS[endpoint_name]
    return url_template.format(pk=graph_rag.graph_rag_id, **url_kwargs)


# -- Every endpoint: happy path, org scoping, permission, upstream errors --


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
def test_endpoint_returns_upstream_data(auth_client, default_org, endpoint_name):
    graph_rag = _make_graph_rag(default_org)
    _, _, client_method, upstream_body = _ENDPOINTS[endpoint_name]

    with patch(client_method, return_value=upstream_body):
        response = auth_client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == status.HTTP_200_OK
    assert response.data == upstream_body


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
def test_endpoint_returns_404_for_graph_rag_of_another_org(auth_client, beta, endpoint_name):  # noqa: F811
    graph_rag = _make_graph_rag(beta)
    _, _, client_method, _ = _ENDPOINTS[endpoint_name]

    with patch(client_method) as upstream:
        response = auth_client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    upstream.assert_not_called()


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
def test_endpoint_refuses_member_without_knowledge_read(
    custom_role_user,  # noqa: F811
    default_org,
    endpoint_name,
):
    user = custom_role_user(
        default_org, "graph-reader-no-knowledge@example.com", {ResourceType.FLOWS: Permission.READ}
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    graph_rag = _make_graph_rag(default_org)
    _, _, client_method, _ = _ENDPOINTS[endpoint_name]

    with patch(client_method) as upstream:
        response = client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    upstream.assert_not_called()


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
def test_endpoint_passes_graph_not_indexed_through_as_409(auth_client, default_org, endpoint_name):
    graph_rag = _make_graph_rag(default_org)
    _, _, client_method, _ = _ENDPOINTS[endpoint_name]
    upstream_error = KnowledgeGraphNotIndexedError('{"code": "graph_not_indexed"}')

    with patch(client_method, side_effect=upstream_error):
        response = auth_client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {"type": "client_error", "errors": [{"code": "graph_not_indexed", "detail": "The graph has not been indexed yet. Run indexing to view it.", "attr": None, "context": None}]}


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
def test_upstream_graph_not_indexed_response_reaches_the_browser_as_409(
    auth_client, default_org, endpoint_name
):
    # The real client runs; only its transport stands in for knowledge_new.
    graph_rag = _make_graph_rag(default_org)
    seen_paths: list[str] = []

    def knowledge_new_without_index_output(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            409,
            json={"code": "graph_not_indexed", "detail": "Graph index output not available."},
        )

    client_over_fake_upstream = partial(
        KnowledgeClient, transport=httpx.MockTransport(knowledge_new_without_index_output)
    )
    with patch(_VIEW_KNOWLEDGE_CLIENT, client_over_fake_upstream):
        response = auth_client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {"type": "client_error", "errors": [{"code": "graph_not_indexed", "detail": "The graph has not been indexed yet. Run indexing to view it.", "attr": None, "context": None}]}
    assert seen_paths == [_UPSTREAM_PATHS[endpoint_name].format(rag_id=graph_rag.graph_rag_id)]


@pytest.mark.parametrize("endpoint_name", _ENDPOINT_NAMES)
@pytest.mark.parametrize(
    ("upstream_error", "expected_status", "expected_code"),
    [
        (ClientResourceNotFoundError("not found"), 404, "upstream_resource_not_found"),
        (ClientBadGatewayError("knowledge_new is down"), 502, "upstream_service_error"),
        (ClientNotAvailableError("refused"), 503, "upstream_service_unreachable"),
        (ClientTimeoutError("timed out"), 504, "upstream_service_timeout"),
    ],
    ids=["upstream-404", "upstream-502", "upstream-503", "upstream-504"],
)
def test_endpoint_maps_upstream_errors_to_error_envelope(
    auth_client, default_org, endpoint_name, upstream_error, expected_status, expected_code
):
    graph_rag = _make_graph_rag(default_org)
    _, _, client_method, _ = _ENDPOINTS[endpoint_name]

    with patch(client_method, side_effect=upstream_error):
        response = auth_client.get(_endpoint_url(endpoint_name, graph_rag))

    assert response.status_code == expected_status
    assert response.data == {
        "type": "client_error" if expected_status < 500 else "server_error",
        "errors": [
            {
                "code": expected_code,
                "detail": upstream_error.public_detail,
                "attr": None,
                "context": None,
            }
        ],
    }


# -- Visualization: parameters --


def test_visualization_forwards_absent_max_entities_and_search_as_none(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_VISUALIZATION_CLIENT, return_value=SAMPLE_VISUALIZATION) as upstream:
        auth_client.get(_endpoint_url("visualization", graph_rag))

    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=None, search=None)


def test_visualization_forwards_search_and_max_entities(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_VISUALIZATION_CLIENT, return_value=SAMPLE_VISUALIZATION) as upstream:
        response = auth_client.get(
            _endpoint_url("visualization", graph_rag), {"max_entities": "100", "search": "C++"}
        )

    assert response.status_code == status.HTTP_200_OK
    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=100, search="C++")


def test_visualization_accepts_max_entities_above_two_thousand(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_VISUALIZATION_CLIENT, return_value=SAMPLE_VISUALIZATION) as upstream:
        response = auth_client.get(
            _endpoint_url("visualization", graph_rag), {"max_entities": "5000"}
        )

    assert response.status_code == status.HTTP_200_OK
    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=5000, search=None)


def test_visualization_forwards_blank_search_as_none(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_VISUALIZATION_CLIENT, return_value=SAMPLE_VISUALIZATION) as upstream:
        auth_client.get(_endpoint_url("visualization", graph_rag), {"search": ""})

    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, max_entities=None, search=None)


@pytest.mark.parametrize(
    ("query", "invalid_parameter"),
    [
        ({"max_entities": "0"}, "max_entities"),
        ({"max_entities": "-3"}, "max_entities"),
        ({"max_entities": "abc"}, "max_entities"),
        ({"search": "x" * 201}, "search"),
    ],
    ids=["max-entities-zero", "max-entities-negative", "max-entities-not-integer", "search-201"],
)
def test_visualization_rejects_invalid_query(auth_client, default_org, query, invalid_parameter):
    graph_rag = _make_graph_rag(default_org)

    with patch(_VISUALIZATION_CLIENT) as upstream:
        response = auth_client.get(_endpoint_url("visualization", graph_rag), query)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["type"] == "client_error"
    assert [item["attr"] for item in response.data["errors"]] == [invalid_parameter]
    upstream.assert_not_called()


# -- Table data: parameters --


def test_table_data_applies_default_paging(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_TABLE_DATA_CLIENT, return_value=SAMPLE_TABLE_DATA) as upstream:
        auth_client.get(_endpoint_url("table-data", graph_rag))

    upstream.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, table_name="entities", page=1, page_size=10, search=None
    )


def test_table_data_forwards_paging_and_search(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_TABLE_DATA_CLIENT, return_value=SAMPLE_TABLE_DATA) as upstream:
        response = auth_client.get(
            _endpoint_url("table-data", graph_rag),
            {"page": "4", "page_size": "100", "search": " C++ "},
        )

    assert response.status_code == status.HTTP_200_OK
    upstream.assert_called_once_with(
        rag_id=graph_rag.graph_rag_id, table_name="entities", page=4, page_size=100, search=" C++ "
    )


def test_table_data_accepts_search_of_two_hundred_characters(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_TABLE_DATA_CLIENT, return_value=SAMPLE_TABLE_DATA):
        response = auth_client.get(_endpoint_url("table-data", graph_rag), {"search": "x" * 200})

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
    ("query", "invalid_parameter"),
    [
        ({"page": "0"}, "page"),
        ({"page": "abc"}, "page"),
        ({"page_size": "-1"}, "page_size"),
        ({"page_size": "0"}, "page_size"),
        ({"page_size": "101"}, "page_size"),
        ({"page_size": "1.5"}, "page_size"),
        ({"search": "x" * 201}, "search"),
    ],
    ids=[
        "page-zero",
        "page-not-integer",
        "page-size-negative",
        "page-size-zero",
        "page-size-101",
        "page-size-not-integer",
        "search-201",
    ],
)
def test_table_data_rejects_invalid_query(auth_client, default_org, query, invalid_parameter):
    graph_rag = _make_graph_rag(default_org)

    with patch(_TABLE_DATA_CLIENT) as upstream:
        response = auth_client.get(_endpoint_url("table-data", graph_rag), query)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["type"] == "client_error"
    assert [item["attr"] for item in response.data["errors"]] == [invalid_parameter]
    upstream.assert_not_called()


# -- Detail: path ids --


def test_entity_detail_forwards_entity_id(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_ENTITY_CLIENT, return_value={"description": "d"}) as upstream:
        auth_client.get(_endpoint_url("entity-detail", graph_rag))

    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, entity_id="e1")


def test_relationship_detail_forwards_relationship_id(auth_client, default_org):
    graph_rag = _make_graph_rag(default_org)

    with patch(_RELATIONSHIP_CLIENT, return_value={"description": "d"}) as upstream:
        auth_client.get(_endpoint_url("relationship-detail", graph_rag))

    upstream.assert_called_once_with(rag_id=graph_rag.graph_rag_id, relationship_id="r1")
