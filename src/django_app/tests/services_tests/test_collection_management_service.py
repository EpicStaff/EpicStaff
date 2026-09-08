"""
Tests for SourceCollection description handling.

Covers the parts of the description feature that are unreachable through the
API test suite (auth baseline is broken there, see
tests/api_tests/knowledge_tests/test_collection_management.py):
- SourceCollectionCreateSerializer / SourceCollectionUpdateSerializer length
  validation on `description`
- CollectionManagementService.create_collection persisting `description`
- CollectionManagementService.copy_collection carrying the source
  `description` onto the copy
"""

from unittest.mock import MagicMock, patch

import pytest

from src.shared.enums.knowledge_new import RAGStrategy
from tables.clients.errors import ClientNotAvailableError
from tables.exceptions import (
    GraphRagMetricsUnavailableException,
    NaiveRagIndexNotReadyException,
    NoNaiveRagForCollectionException,
)
from tables.models.knowledge_models import GraphRag, NaiveRag
from tables.serializers.knowledge_serializers import (
    COLLECTION_DESCRIPTION_MAX_LENGTH,
    SourceCollectionCreateSerializer,
    SourceCollectionUpdateSerializer,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)

MODULE = "tables.services.knowledge_services.collection_management_service"


class TestSourceCollectionCreateSerializerDescriptionValidation:
    def test_description_over_limit_rejected(self):
        serializer = SourceCollectionCreateSerializer(
            data={
                "collection_name": "Overlong Description Collection",
                "description": "x" * (COLLECTION_DESCRIPTION_MAX_LENGTH + 1),
            }
        )

        assert serializer.is_valid() is False
        assert "description" in serializer.errors

    def test_description_at_limit_accepted(self):
        serializer = SourceCollectionCreateSerializer(
            data={
                "collection_name": "At Limit Description Collection",
                "description": "x" * COLLECTION_DESCRIPTION_MAX_LENGTH,
            }
        )

        assert serializer.is_valid() is True


class TestSourceCollectionUpdateSerializerDescriptionValidation:
    def test_description_over_limit_rejected(self):
        serializer = SourceCollectionUpdateSerializer(
            data={
                "collection_name": "Existing Name",
                "description": "x" * (COLLECTION_DESCRIPTION_MAX_LENGTH + 1),
            }
        )

        assert serializer.is_valid() is False
        assert "description" in serializer.errors

    def test_description_at_limit_accepted(self):
        serializer = SourceCollectionUpdateSerializer(
            data={
                "collection_name": "Existing Name",
                "description": "x" * COLLECTION_DESCRIPTION_MAX_LENGTH,
            }
        )

        assert serializer.is_valid() is True


class TestCreateCollectionPersistsDescription:
    @pytest.mark.django_db
    def test_create_collection_persists_description(self, default_org):
        collection = CollectionManagementService.create_collection(
            collection_name="Documented Collection",
            description="Contains onboarding docs for new hires.",
            org_id=default_org.pk,
        )

        collection.refresh_from_db()
        assert collection.description == "Contains onboarding docs for new hires."


class TestCopyCollectionCarriesDescription:
    @pytest.mark.django_db
    def test_copy_collection_carries_source_description(self, default_org):
        source_collection = CollectionManagementService.create_collection(
            collection_name="Source Collection",
            description="Source description.",
            org_id=default_org.pk,
        )

        copied_collection = CollectionManagementService.copy_collection(
            source_collection_id=source_collection.collection_id,
            org_id=default_org.pk,
        )

        assert copied_collection.description == "Source description."

    @pytest.mark.django_db
    def test_copy_collection_with_blank_source_description_stays_blank(
        self, default_org
    ):
        source_collection = CollectionManagementService.create_collection(
            collection_name="Blank Description Source",
            org_id=default_org.pk,
        )

        copied_collection = CollectionManagementService.copy_collection(
            source_collection_id=source_collection.collection_id,
            org_id=default_org.pk,
        )

        assert copied_collection.description == ""


class TestGetGraphMetrics:
    """_get_graph_metrics fetches chunk metrics from knowledge_new over REST."""

    def _completed_graph_rag(self):
        graph_rag = MagicMock()
        graph_rag.rag_status = GraphRag.GraphRagStatus.COMPLETED
        graph_rag.graph_rag_id = 5
        graph_rag.graph_rag_documents.count.return_value = 3
        return graph_rag

    @patch(f"{MODULE}.KnowledgeClient")
    @patch(f"{MODULE}.GraphRagService")
    def test_returns_chunk_metrics_from_client(self, mock_service, mock_client_cls):
        mock_service.get_or_none_graph_rag_by_collection.return_value = (
            self._completed_graph_rag()
        )
        client = mock_client_cls.return_value.__enter__.return_value
        client.metrics.return_value = {"total_chunks": 42, "avg_chunk_size": 128.5}

        metrics = CollectionManagementService._get_graph_metrics(collection_id=1)

        client.metrics.assert_called_once_with(RAGStrategy.GRAPH, 5)
        assert metrics.total_documents == 3
        assert metrics.total_chunks == 42
        assert metrics.avg_chunk_size == 128.5

    @patch(f"{MODULE}.KnowledgeClient")
    @patch(f"{MODULE}.GraphRagService")
    def test_client_failure_raises_metrics_unavailable(
        self, mock_service, mock_client_cls
    ):
        mock_service.get_or_none_graph_rag_by_collection.return_value = (
            self._completed_graph_rag()
        )
        client = mock_client_cls.return_value.__enter__.return_value
        client.metrics.side_effect = ClientNotAvailableError("down")

        with pytest.raises(GraphRagMetricsUnavailableException):
            CollectionManagementService._get_graph_metrics(collection_id=1)


class TestGetNaiveMetrics:
    """_get_naive_metrics gates on NaiveRag existence and readiness."""

    @patch(f"{MODULE}.NaiveRagService")
    def test_missing_naive_rag_raises(self, mock_service):
        mock_service.get_or_none_naive_rag_by_collection.return_value = None

        with pytest.raises(NoNaiveRagForCollectionException):
            CollectionManagementService._get_naive_metrics(collection_id=1)

    @patch(f"{MODULE}.NaiveRagService")
    def test_not_completed_naive_rag_raises(self, mock_service):
        naive_rag = MagicMock()
        naive_rag.rag_status = NaiveRag.NaiveRagStatus.NEW
        mock_service.get_or_none_naive_rag_by_collection.return_value = naive_rag

        with pytest.raises(NaiveRagIndexNotReadyException):
            CollectionManagementService._get_naive_metrics(collection_id=1)
