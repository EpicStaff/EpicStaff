"""A failed call to knowledge_new from an indexing or chunking endpoint keeps its status
and answers with the project's error envelope, never with knowledge_new's response body.

Only the HTTP exchange with knowledge_new is replaced, so the knowledge client's own
status mapping runs as in production. Any other outbound HTTP request fails the test.
"""

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
from django.urls import reverse
from rest_framework import status

from tables.clients.knowledge import KnowledgeClient

pytestmark = pytest.mark.django_db

# A knowledge_new error body naming an internal host and file path.
UPSTREAM_BODY = (
    '{"code": "internal_error", "detail": "Traceback: File \\"/app/knowledge-internal/rag.py\\", '
    'connection to qdrant at 10.0.0.9:6333 refused"}'
)
UPSTREAM_FRAGMENTS = ("knowledge-internal", "10.0.0.9", "Traceback")
KNOWLEDGE_SERVICE = httpx.URL(KnowledgeClient.HOST)


@dataclass(frozen=True)
class Endpoint:
    name: str
    call: Callable  # (client, naive_rag_document_config) -> response


def _process_chunking(client, config):
    return client.post(
        reverse("process-document-chunking", args=[config.naive_rag_id, config.pk]),
        {"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150},
        format="json",
    )


def _cancel_chunking(client, config):
    return client.delete(reverse("cancel-document-chunking", args=[config.naive_rag_id, config.pk]))


def _process_indexing(client, config):
    return client.post(
        reverse("process-rag-indexing"),
        {"rag_id": config.naive_rag_id, "rag_type": "naive", "document_config_ids": [config.pk]},
        format="json",
    )


def _indexing_estimate(client, config):
    return client.post(
        reverse("process-rag-indexing-estimate"),
        {"rag_id": config.naive_rag_id, "rag_type": "naive", "document_config_ids": [config.pk]},
        format="json",
    )


def _cancel_indexing(client, config):
    return client.delete(reverse("cancel-rag-indexing", args=["naive", config.naive_rag_id]))


ENDPOINTS = [
    Endpoint("process_chunking", _process_chunking),
    Endpoint("cancel_chunking", _cancel_chunking),
    Endpoint("process_indexing", _process_indexing),
    Endpoint("indexing_estimate", _indexing_estimate),
    Endpoint("cancel_indexing", _cancel_indexing),
]


def _answer(status_code):
    def respond(method, url):
        return httpx.Response(status_code, text=UPSTREAM_BODY, request=httpx.Request(method, url))

    return respond


def _time_out(method, url):
    raise httpx.ReadTimeout("timed out", request=httpx.Request(method, url))


class FakeKnowledgeService:
    """Stands in for knowledge_new; `respond` decides how it answers."""

    def __init__(self):
        self.respond: Callable = _answer(200)
        self.unexpected_requests: list[str] = []


@pytest.fixture
def knowledge_service(monkeypatch):
    service = FakeKnowledgeService()

    def fake_request(client, method, url, **kwargs):
        target = client.base_url.join(url)
        if target.host != KNOWLEDGE_SERVICE.host or target.port != KNOWLEDGE_SERVICE.port:
            # Recorded as well as raised: the view under test may swallow the exception.
            service.unexpected_requests.append(f"{method} {target}")
            raise AssertionError(f"Unexpected outbound request: {method} {target}")
        return service.respond(method, target)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    yield service
    assert not service.unexpected_requests, f"Requests outside knowledge_new: {service.unexpected_requests}"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=[endpoint.name for endpoint in ENDPOINTS])
@pytest.mark.parametrize(
    "upstream, expected_status, expected_code, expected_message",
    [
        (
            _answer(500),
            status.HTTP_502_BAD_GATEWAY,
            "upstream_service_error",
            "An upstream service failed to handle the request.",
        ),
        (
            _answer(400),
            status.HTTP_400_BAD_REQUEST,
            "upstream_service_rejected",
            "An upstream service rejected the request.",
        ),
        (
            _answer(409),
            status.HTTP_409_CONFLICT,
            "upstream_resource_conflict",
            "The upstream resource is not in a state that allows the request.",
        ),
        (
            _time_out,
            status.HTTP_504_GATEWAY_TIMEOUT,
            "upstream_service_timeout",
            "An upstream service timed out.",
        ),
    ],
    ids=["upstream-500", "upstream-400", "upstream-409", "timeout"],
)
def test_knowledge_service_failure_keeps_its_status_without_the_upstream_body(
    endpoint,
    upstream,
    expected_status,
    expected_code,
    expected_message,
    auth_client,
    naive_rag_document_config,
    knowledge_service,
):
    knowledge_service.respond = upstream

    response = endpoint.call(auth_client, naive_rag_document_config)

    assert response.status_code == expected_status
    assert response.json() == {
        "status_code": expected_status,
        "code": expected_code,
        "message": expected_message,
    }
    for fragment in UPSTREAM_FRAGMENTS:
        assert fragment not in response.content.decode()
