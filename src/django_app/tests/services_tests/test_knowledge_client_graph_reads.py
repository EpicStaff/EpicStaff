"""KnowledgeClient's graph index reads, against a fake knowledge_new behind httpx.MockTransport.

The transport is the HTTP boundary; everything above it (URL building, status mapping)
is the real client.
"""

import httpx
import pytest

from tables.clients.errors import (
    ClientConflictError,
    ClientResourceNotFoundError,
    ClientValidationError,
    KnowledgeGraphNotIndexedError,
)
from tables.clients.knowledge import KnowledgeClient


def _client_answering(status_code: int, body: object, seen_requests: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(status_code, json=body)

    return KnowledgeClient(transport=httpx.MockTransport(handle))


def test_entity_id_is_sent_as_one_encoded_path_segment():
    seen_requests: list[httpx.Request] = []
    with _client_answering(200, {"description": "x"}, seen_requests) as client:
        client.get_entity_detail(rag_id=7, entity_id="a/b?c#d e")

    assert seen_requests[0].url.raw_path == b"/rags/graph/7/entity/a%2Fb%3Fc%23d%20e/"


def test_relationship_id_is_sent_as_one_encoded_path_segment():
    seen_requests: list[httpx.Request] = []
    with _client_answering(200, {"description": "x"}, seen_requests) as client:
        client.get_relationship_detail(rag_id=7, relationship_id="../metrics")

    assert seen_requests[0].url.raw_path == b"/rags/graph/7/relationship/..%2Fmetrics/"


def test_table_data_forwards_paging_and_search_as_query_params():
    seen_requests: list[httpx.Request] = []
    with _client_answering(200, {"rows": []}, seen_requests) as client:
        client.get_table_data(rag_id=7, table_name="entities", page=3, page_size=25, search="C++")

    url = seen_requests[0].url
    assert url.path == "/rags/graph/7/tables/entities/"
    assert dict(url.params) == {"page": "3", "page_size": "25", "search": "C++"}


def test_visualization_omits_max_entities_when_not_given():
    seen_requests: list[httpx.Request] = []
    with _client_answering(200, {"entities": []}, seen_requests) as client:
        client.get_visualization(rag_id=7)

    assert "max_entities" not in seen_requests[0].url.params


def test_upstream_graph_not_indexed_conflict_raises_not_indexed_error():
    body = {"code": "graph_not_indexed", "detail": "Run indexing first."}
    with _client_answering(409, body, []) as client:
        with pytest.raises(KnowledgeGraphNotIndexedError) as raised:
            client.get_visualization(rag_id=7)

    assert raised.value.status_code == 409
    assert raised.value.code == "graph_not_indexed"


def test_upstream_conflict_with_another_code_raises_generic_conflict_error():
    with _client_answering(409, {"code": "something_else", "detail": "no"}, []) as client:
        with pytest.raises(ClientConflictError) as raised:
            client.get_table_summary(rag_id=7)

    assert type(raised.value) is ClientConflictError
    assert raised.value.status_code == 409


def test_upstream_conflict_without_json_body_raises_generic_conflict_error():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="conflict")

    with KnowledgeClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ClientConflictError) as raised:
            client.get_table_summary(rag_id=7)

    assert type(raised.value) is ClientConflictError


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(404, ClientResourceNotFoundError), (400, ClientValidationError)],
)
def test_other_upstream_client_errors_keep_their_mapping(status_code, expected_error):
    with _client_answering(status_code, {"code": "x", "detail": "y"}, []) as client:
        with pytest.raises(expected_error):
            client.get_entity_detail(rag_id=7, entity_id="e1")
