"""Cancelling a RAG's indexing or a document's chunking: both ask knowledge_new to stop.

knowledge_new answering 404 means nothing was running (a no-op, 204). How an upstream
failure reaches the caller is covered in
test_knowledge_service_errors_on_indexing_and_chunking.py. The knowledge client is
the HTTP boundary to knowledge_new, so it is the only thing replaced.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from tables.clients.errors import ClientResourceNotFoundError

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["rag-indexing", "document-chunking"])
def cancel_url(request, naive_rag_document_config):
    if request.param == "rag-indexing":
        return reverse("cancel-rag-indexing", args=["naive", naive_rag_document_config.naive_rag_id])
    return reverse(
        "cancel-document-chunking", args=[naive_rag_document_config.naive_rag_id, naive_rag_document_config.pk]
    )


def test_cancel_with_nothing_running_is_a_no_op(auth_client, cancel_url):
    with patch(
        "tables.clients.knowledge.KnowledgeClient.cancel",
        side_effect=ClientResourceNotFoundError("no running operation"),
    ):
        response = auth_client.delete(cancel_url)

    assert response.status_code == status.HTTP_204_NO_CONTENT
