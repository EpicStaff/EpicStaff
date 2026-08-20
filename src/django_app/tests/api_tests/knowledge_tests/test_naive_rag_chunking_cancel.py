"""
Happy-path test for CancelNaiveRagDocumentChunkingView.

Verifies that POSTing to the cancel endpoint:
- returns HTTP 202 with the expected detail body
- publishes exactly one message on the correct channel
- the published target_request reproduces the PrechunkRequest hash key
  byte-for-byte (rag_strategy, rag_id, document_id == config pk, chunking params, extra)
"""

from unittest.mock import patch

import pytest
from django.conf import settings
from django.urls import reverse


@pytest.mark.django_db
class TestCancelNaiveRagDocumentChunkingView:
    def test_cancel_publishes_correct_prechunk_request(
        self, auth_client, naive_rag_document_config
    ):
        naive_rag_id = naive_rag_document_config.naive_rag_id
        document_config_id = naive_rag_document_config.naive_rag_document_id

        url = reverse(
            "cancel-document-chunking",
            args=[naive_rag_id, document_config_id],
        )
        body = {
            "chunk_strategy": naive_rag_document_config.chunk_strategy,
            "chunk_size": naive_rag_document_config.chunk_size,
            "chunk_overlap": naive_rag_document_config.chunk_overlap,
        }

        with patch("tables.views.knowledge_views.naive_rag_views.producer") as mock_producer:
            response = auth_client.post(url, body, format="json")

        assert response.status_code == 202
        assert response.data == {
            "detail": "Chunking cancellation requested",
            "naive_rag_id": naive_rag_id,
            "document_config_id": document_config_id,
        }

        mock_producer.send.assert_called_once()
        channel, message = mock_producer.send.call_args.args
        assert channel == settings.KNOWLEDGE_CANCEL_REQUEST_CHANNEL
        assert message.payload["target_request"] == {
            "rag_strategy": "naive",
            "rag_id": naive_rag_id,
            "document_id": document_config_id,
            "chunk_strategy": naive_rag_document_config.chunk_strategy,
            "chunk_size": naive_rag_document_config.chunk_size,
            "chunk_overlap": naive_rag_document_config.chunk_overlap,
            "extra": {},
        }
