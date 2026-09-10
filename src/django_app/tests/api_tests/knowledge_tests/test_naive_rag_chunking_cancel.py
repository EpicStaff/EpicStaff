"""
Tests for CancelNaiveRagDocumentChunkingView.

Covers the 404 → 204 no-op path (nothing running to cancel) and the
upstream failure path (5xx) which must surface as an error response.
"""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from tables.clients.errors import ClientBadGatewayError, ClientResourceNotFoundError


@pytest.mark.django_db
class TestCancelNaiveRagDocumentChunkingView:
    def _url(self, naive_rag_id: int, document_config_id: int) -> str:
        return reverse(
            "cancel-document-chunking",
            args=[naive_rag_id, document_config_id],
        )

    def test_upstream_404_returns_204(self, auth_client, naive_rag_document_config):
        """knowledge_new 404 (no running operation) is a no-op — caller gets 204."""
        naive_rag_id = naive_rag_document_config.naive_rag_id
        document_config_id = naive_rag_document_config.id

        with patch(
            "tables.clients.knowledge.KnowledgeClient.cancel",
            side_effect=ClientResourceNotFoundError("no running operation"),
        ):
            response = auth_client.delete(self._url(naive_rag_id, document_config_id))

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_upstream_5xx_returns_error(self, auth_client, naive_rag_document_config):
        """Upstream service failure must not be swallowed — caller gets the error status."""
        naive_rag_id = naive_rag_document_config.naive_rag_id
        document_config_id = naive_rag_document_config.id

        with patch(
            "tables.clients.knowledge.KnowledgeClient.cancel",
            side_effect=ClientBadGatewayError("knowledge_new is down"),
        ):
            response = auth_client.delete(self._url(naive_rag_id, document_config_id))

        assert response.status_code == 502
        assert "error" in response.data
