"""An unexpected exception in a knowledge endpoint answers with the generic 500
envelope: its text, which can carry database driver internals, is logged
server-side with the traceback and never returned to the caller."""

import logging
from dataclasses import dataclass
from typing import Callable

import pytest
from django.db import OperationalError
from django.urls import reverse
from rest_framework import status

from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientResourceNotFoundError,
    ClientTimeoutError,
    ClientValidationError,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService

# A knowledge service error page naming an internal host and file path.
UPSTREAM_BODY = (
    'Traceback (most recent call last): File "/app/knowledge-internal/rag.py", line 12'
)
DRIVER_ERROR_TEXT = (
    'connection to server at "crewdb" (172.18.0.5), port 5432 failed: '
    'FATAL: password authentication failed for user "postgres"'
)


@dataclass(frozen=True)
class FailingEndpoint:
    name: str
    service: type
    service_method: str
    call: Callable  # (client, request fixture accessor) -> response


def _create_collection(client, fixture):
    return client.post(
        reverse("sourcecollection-list"), {"collection_name": "New"}, format="json"
    )


def _delete_document(client, fixture):
    document = fixture("document_metadata")
    return client.delete(reverse("document-detail", args=[document.document_id]))


def _get_graph_rag_by_collection(client, fixture):
    collection = fixture("source_collection")
    return client.get(
        reverse("graph-rag-collection", kwargs={"collection_id": collection.collection_id})
    )


def _get_naive_rag_by_collection(client, fixture):
    collection = fixture("source_collection")
    return client.get(
        reverse("naive-rag-collection", kwargs={"collection_id": collection.collection_id})
    )


def _get_naive_rag(client, fixture):
    naive_rag = fixture("naive_rag")
    return client.get(reverse("naive-rag-detail", kwargs={"pk": naive_rag.naive_rag_id}))


FAILING_ENDPOINTS = [
    FailingEndpoint(
        "collection_create", CollectionManagementService, "create_collection", _create_collection
    ),
    FailingEndpoint(
        "document_destroy", DocumentManagementService, "delete_document", _delete_document
    ),
    FailingEndpoint(
        "graph_rag_by_collection",
        GraphRagService,
        "get_or_none_graph_rag_by_collection",
        _get_graph_rag_by_collection,
    ),
    FailingEndpoint(
        "naive_rag_by_collection",
        NaiveRagService,
        "get_or_none_naive_rag_by_collection",
        _get_naive_rag_by_collection,
    ),
    FailingEndpoint("naive_rag_retrieve", NaiveRagService, "get_naive_rag", _get_naive_rag),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "endpoint", FAILING_ENDPOINTS, ids=[endpoint.name for endpoint in FAILING_ENDPOINTS]
)
def test_unexpected_error_is_logged_and_not_returned(
    endpoint, auth_client, mocker, request, caplog, monkeypatch
):
    # With DEBUG on the handler re-raises instead of rendering the generic 500.
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    driver_error = OperationalError(DRIVER_ERROR_TEXT)
    mocker.patch.object(endpoint.service, endpoint.service_method, side_effect=driver_error)

    with caplog.at_level(logging.ERROR, logger="django.request"):
        response = endpoint.call(auth_client, request.getfixturevalue)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["message"] == "Unpredictable error"
    assert "crewdb" not in response.content.decode()
    assert "password authentication" not in response.content.decode()

    request_log = [
        (record.levelno, record.exc_info and record.exc_info[1])
        for record in caplog.records
        if record.name == "django.request"
    ]
    assert request_log == [(logging.ERROR, driver_error)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "client_error, expected_status, expected_message",
    [
        (ClientNotAvailableError("Knowledge service is unreachable."), 503,
         "An upstream service is unreachable."),
        (ClientTimeoutError("Knowledge service timed out."), 504,
         "An upstream service timed out."),
        (ClientBadGatewayError(UPSTREAM_BODY), 502,
         "An upstream service failed to handle the request."),
        (ClientValidationError(UPSTREAM_BODY), 400,
         "An upstream service rejected the request."),
        (ClientResourceNotFoundError(UPSTREAM_BODY), 404,
         "The upstream resource was not found."),
    ],
    ids=["unreachable", "timeout", "bad_gateway", "rejected", "not_found"],
)
def test_knowledge_service_error_keeps_its_status_without_upstream_text(
    client_error, expected_status, expected_message, auth_client, mocker, request, monkeypatch
):
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    naive_rag = request.getfixturevalue("naive_rag")
    mocker.patch.object(NaiveRagService, "delete_naive_rag", side_effect=client_error)

    response = auth_client.delete(reverse("naive-rag-detail", kwargs={"pk": naive_rag.naive_rag_id}))

    assert response.status_code == expected_status
    assert response.json()["message"] == expected_message
    assert "Traceback" not in response.content.decode()
    assert "knowledge-internal" not in response.content.decode()
