from typing import Dict, Any
from django.db import transaction
from loguru import logger

from tables.models.knowledge_models import (
    NaiveRag,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
)
from tables.exceptions import (
    NaiveRagNotFoundException,
    GraphRagNotFoundException,
    CollectionNotFoundException,
    DocumentsNotFoundException,
    RagException,
    RagNotReadyForIndexingException,
)


class IndexingService:
    """
    Service for RAG indexing operations.

    Handles:
    - Validating RAG configurations
    - Preparing data for indexing (chunking + embedding)
    - Business logic for triggering indexing process
    """

    @staticmethod
    @transaction.atomic
    def validate_and_prepare_indexing(rag_id: int, rag_type: str) -> Dict[str, Any]:
        """
        Validates RAG configuration and prepares data for indexing.

        Args:
            rag_id: The primary key of the specific RAG implementation
            rag_type: The type of RAG ("naive" or "graph")

        Returns:
            Dict containing:
                - rag_id: int
                - rag_type: str
                - collection_id: int
                - base_rag_type_id: int
        """
        if rag_type == "naive":
            return IndexingService._prepare_naive_rag_indexing(rag_id)
        elif rag_type == "graph":
            return IndexingService._prepare_graph_rag_indexing(rag_id)
        else:
            raise RagException(f"Unknown rag_type: {rag_type}")

    @staticmethod
    def _prepare_naive_rag_indexing(naive_rag_id: int) -> Dict[str, Any]:
        """
        Validates and prepares NaiveRag for indexing.

        Args:
            naive_rag_id: The NaiveRag primary key

        Returns:
            Dict with rag_id, rag_type, collection_id, base_rag_type_id
        """
        # Get NaiveRag instance
        try:
            naive_rag = NaiveRag.objects.select_related(
                "base_rag_type", "base_rag_type__source_collection", "embedder"
            ).get(naive_rag_id=naive_rag_id)
        except NaiveRag.DoesNotExist:
            raise NaiveRagNotFoundException(naive_rag_id)

        # Get related objects
        base_rag_type = naive_rag.base_rag_type
        collection = base_rag_type.source_collection

        # Validate collection exists
        if not collection:
            raise CollectionNotFoundException(
                f"Collection not found for BaseRagType {base_rag_type.rag_type_id}"
            )

        # Validate collection has documents
        document_count = DocumentMetadata.objects.filter(
            source_collection=collection
        ).count()

        if document_count == 0:
            raise DocumentsNotFoundException(
                f"Collection {collection.collection_id} has no documents to index"
            )

        # Validate embedder is configured
        if not naive_rag.embedder:
            raise RagNotReadyForIndexingException(
                f"NaiveRag {naive_rag_id} has no embedder configured. "
                "Please configure an embedder before indexing."
            )

        # Log preparation
        logger.info(
            f"Prepared NaiveRag {naive_rag_id} for indexing: "
            f"collection_id={collection.collection_id}, "
            f"documents={document_count}, "
            f"embedder={naive_rag.embedder.id}"
        )

        return {
            "rag_id": naive_rag_id,
            "rag_type": "naive",
            "collection_id": collection.collection_id,
            "base_rag_type_id": base_rag_type.rag_type_id,
        }

    @staticmethod
    def _prepare_graph_rag_indexing(graph_rag_id: int) -> Dict[str, Any]:
        """
        Validates and prepares GraphRag for indexing.

        Args:
            graph_rag_id: The GraphRag primary key

        Returns:
            Dict with rag_id, rag_type, collection_id, base_rag_type_id
        """
        # Get GraphRag instance
        try:
            graph_rag = GraphRag.objects.select_related(
                "base_rag_type",
                "base_rag_type__source_collection",
                "embedder",
                "llm",
                "index_config",
            ).get(graph_rag_id=graph_rag_id)
        except GraphRag.DoesNotExist:
            raise GraphRagNotFoundException(graph_rag_id)

        # Get related objects
        base_rag_type = graph_rag.base_rag_type
        collection = base_rag_type.source_collection

        # Validate collection exists
        if not collection:
            raise CollectionNotFoundException(
                f"Collection not found for BaseRagType {base_rag_type.rag_type_id}"
            )

        # Validate GraphRag has documents linked
        document_count = GraphRagDocument.objects.filter(
            graph_rag=graph_rag
        ).count()

        if document_count == 0:
            raise RagNotReadyForIndexingException(
                f"GraphRag {graph_rag_id} has no documents. "
                "Please add documents before indexing."
            )

        # Validate embedder is configured
        if not graph_rag.embedder:
            raise RagNotReadyForIndexingException(
                f"GraphRag {graph_rag_id} has no embedder configured. "
                "Please configure an embedder before indexing."
            )

        # Validate LLM is configured (required for entity extraction)
        if not graph_rag.llm:
            raise RagNotReadyForIndexingException(
                f"GraphRag {graph_rag_id} has no LLM configured. "
                "Please configure an LLM before indexing."
            )

        # Validate index config exists
        if not graph_rag.index_config:
            raise RagNotReadyForIndexingException(
                f"GraphRag {graph_rag_id} has no index configuration. "
                "Please configure index settings before indexing."
            )

        # Log preparation
        logger.info(
            f"Prepared GraphRag {graph_rag_id} for indexing: "
            f"collection_id={collection.collection_id}, "
            f"documents={document_count}, "
            f"embedder={graph_rag.embedder.id}, "
            f"llm={graph_rag.llm.id}"
        )

        return {
            "rag_id": graph_rag_id,
            "rag_type": "graph",
            "collection_id": collection.collection_id,
            "base_rag_type_id": base_rag_type.rag_type_id,
        }

    @staticmethod
    def get_rag_status(rag_id: int, rag_type: str) -> str:
        """
        Get current status of RAG implementation.

        Args:
            rag_id: The RAG primary key
            rag_type: The type of RAG

        Returns:
            Status string
        """
        if rag_type == "naive":
            try:
                naive_rag = NaiveRag.objects.get(naive_rag_id=rag_id)
                return naive_rag.rag_status
            except NaiveRag.DoesNotExist:
                raise NaiveRagNotFoundException(rag_id)
        elif rag_type == "graph":
            try:
                graph_rag = GraphRag.objects.get(graph_rag_id=rag_id)
                return graph_rag.rag_status
            except GraphRag.DoesNotExist:
                raise GraphRagNotFoundException(rag_id)
        else:
            raise RagException(f"Unknown rag_type: {rag_type}")
