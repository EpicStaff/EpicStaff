"""Cancelling a RAG's indexing or a document's chunking: both ask knowledge_new to stop.

knowledge_new answering 404 means nothing was running (a no-op, 204); an upstream
failure must reach the caller instead of being swallowed. The knowledge client is
the HTTP boundary to knowledge_new, so it is the only thing replaced.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from tables.clients.errors import ClientBadGatewayError, ClientResourceNotFoundError

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["rag-indexing", "document-chunking"])
def cancel_url(request, naive_rag_document_config):
    if request.param == "rag-indexing":
        return reverse("cancel-rag-indexing", args=["naive", naive_rag_document_config.naive_rag_id])
    return reverse(
        "cancel-document-chunking", args=[naive_rag_document_config.naive_rag_id, naive_rag_document_config.pk]
    )


@pytest.mark.parametrize(
    ("upstream_error", "expected_status"),
    [
        (ClientResourceNotFoundError("no running operation"), status.HTTP_204_NO_CONTENT),
        (ClientBadGatewayError("knowledge_new is down"), status.HTTP_502_BAD_GATEWAY),
    ],
    ids=["nothing-running", "knowledge-down"],
)
def test_cancel_maps_the_knowledge_service_answer(auth_client, cancel_url, upstream_error, expected_status):
    with patch("tables.clients.knowledge.KnowledgeClient.cancel", side_effect=upstream_error):
        response = auth_client.delete(cancel_url)

    assert response.status_code == expected_status
    if expected_status >= 400:
        assert "error" in response.data
