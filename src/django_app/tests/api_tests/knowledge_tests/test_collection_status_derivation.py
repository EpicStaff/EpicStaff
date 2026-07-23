"""
Tests for the derived SourceCollection status (empty/uploading/completed/
warning/failed), computed at read time by CollectionStatusService and
exposed as SourceCollectionListSerializer/SourceCollectionDetailSerializer's
`status` field - the same vocabulary/mapping the knowledge worker's SSE
progress events use (see src.shared.models.derive_collection_status).
"""

import pytest
from django.urls import reverse
from rest_framework import status as http_status

from tables.models.knowledge_models import BaseRagType, NaiveRag
from tables.services.knowledge_services.collection_status_service import (
    CollectionStatusService,
)


@pytest.mark.django_db
class TestCollectionStatusService:
    """Direct tests of the aggregation logic against real DB rows."""

    def test_empty_collection_has_empty_status(self, empty_collection):
        assert (
            CollectionStatusService.get_collection_status(empty_collection) == "empty"
        )

    def test_collection_with_documents_but_no_rag_is_uploading(
        self, source_collection, document_metadata
    ):
        assert (
            CollectionStatusService.get_collection_status(source_collection)
            == "uploading"
        )

    def test_processing_rag_is_uploading(
        self, source_collection, document_metadata, naive_rag
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.PROCESSING
        naive_rag.save()
        source_collection.refresh_from_db()

        assert (
            CollectionStatusService.get_collection_status(source_collection)
            == "uploading"
        )

    def test_completed_rag_is_completed(
        self, source_collection, document_metadata, naive_rag
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save()
        source_collection.refresh_from_db()

        assert (
            CollectionStatusService.get_collection_status(source_collection)
            == "completed"
        )

    def test_failed_rag_is_failed(
        self, source_collection, document_metadata, naive_rag
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.FAILED
        naive_rag.save()
        source_collection.refresh_from_db()

        assert (
            CollectionStatusService.get_collection_status(source_collection) == "failed"
        )

    def test_mixed_completed_and_failed_rags_is_warning(
        self, source_collection, document_metadata, naive_rag, test_embedding_config
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save()

        second_base_rag_type = BaseRagType.objects.create(
            source_collection=source_collection, rag_type=BaseRagType.RagType.NAIVE
        )
        NaiveRag.objects.create(
            base_rag_type=second_base_rag_type,
            embedder=test_embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.FAILED,
        )
        source_collection.refresh_from_db()

        assert (
            CollectionStatusService.get_collection_status(source_collection)
            == "warning"
        )

    def test_never_stuck_never_returns_stale_uploading_after_terminal_transition(
        self, source_collection, document_metadata, naive_rag
    ):
        """Regression guard: once the underlying NaiveRag reaches a terminal
        rag_status, the derived collection status must reflect it - not stay
        on "uploading" from an earlier read."""
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.PROCESSING
        naive_rag.save()
        source_collection.refresh_from_db()
        assert (
            CollectionStatusService.get_collection_status(source_collection)
            == "uploading"
        )

        naive_rag.rag_status = NaiveRag.NaiveRagStatus.FAILED
        naive_rag.save()
        source_collection.refresh_from_db()
        assert (
            CollectionStatusService.get_collection_status(source_collection) == "failed"
        )


@pytest.mark.django_db
class TestCollectionStatusOverAPI:
    """End-to-end: the REST wire contract renders the derived status."""

    def test_list_renders_derived_status(
        self, auth_client, source_collection, document_metadata, naive_rag
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.FAILED
        naive_rag.save()

        url = reverse("sourcecollection-list")
        response = auth_client.get(url)

        assert response.status_code == http_status.HTTP_200_OK
        [item] = [
            item
            for item in response.json()
            if item["collection_id"] == source_collection.collection_id
        ]
        assert item["status"] == "failed"

    def test_detail_renders_derived_status(
        self, auth_client, source_collection, document_metadata, naive_rag
    ):
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
        naive_rag.save()

        url = reverse("sourcecollection-detail", args=[source_collection.collection_id])
        response = auth_client.get(url)

        assert response.status_code == http_status.HTTP_200_OK
        assert response.json()["status"] == "completed"
