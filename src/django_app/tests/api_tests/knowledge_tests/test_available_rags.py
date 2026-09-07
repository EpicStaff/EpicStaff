"""Tests for GET /source-collections/{id}/available-rags/ — listing the RAGs a
collection exposes, with optional status filtering."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.knowledge_models import NaiveRag


@pytest.fixture
def completed_naive_rag(naive_rag):
    """Update naive_rag status to COMPLETED."""
    naive_rag.rag_status = NaiveRag.NaiveRagStatus.COMPLETED
    naive_rag.save()
    return naive_rag


@pytest.mark.django_db
class TestGetAvailableRags:
    """Tests for GET /source-collections/{id}/available-rags/ endpoint."""

    def test_get_available_rags_for_collection(
        self, auth_client, source_collection, completed_naive_rag
    ):
        """Test getting available RAGs for a collection."""
        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert isinstance(data, list)
        assert len(data) >= 1

        # Verify RAG data structure
        rag_data = data[0]
        assert rag_data["rag_id"] == completed_naive_rag.naive_rag_id
        assert rag_data["rag_type"] == "naive"
        assert rag_data["rag_status"] == NaiveRag.NaiveRagStatus.COMPLETED
        assert rag_data["collection_id"] == source_collection.collection_id
        assert "created_at" in rag_data
        assert "updated_at" in rag_data

    def test_get_available_rags_default_status_filter(
        self, auth_client, source_collection, naive_rag
    ):
        """Test default status filter includes 'completed', 'warning', 'new'."""
        # Set status to NEW
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.NEW
        naive_rag.save()

        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should include NEW status by default
        assert len(data) >= 1

    def test_get_available_rags_custom_status_filter(
        self, auth_client, source_collection, naive_rag
    ):
        """Test filtering by specific status."""
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.PROCESSING
        naive_rag.save()

        url = reverse(
            "sourcecollection-available-rags", args=[source_collection.collection_id]
        )

        # Filter only 'processing' status
        response = auth_client.get(url, {"status": "processing"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert len(data) >= 1
        assert data[0]["rag_status"] == NaiveRag.NaiveRagStatus.PROCESSING

    def test_get_available_rags_empty_collection(self, auth_client, empty_collection):
        """Test getting RAGs for collection without any RAGs."""
        url = reverse(
            "sourcecollection-available-rags", args=[empty_collection.collection_id]
        )

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_available_rags_nonexistent_collection(self, auth_client):
        """Test getting RAGs for non-existent collection."""
        url = reverse("sourcecollection-available-rags", args=[99999])

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
