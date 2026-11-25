from typing import Any

from ai_models.services.config_parameters import (
    embedding_config_parameters,
    llm_config_parameters,
)
from ai_models.services.connection_arguments import (
    embedding_config_connection,
    llm_config_connection,
)
from django.db import transaction
from loguru import logger
from tables.exceptions import (
    CollectionNotFoundException,
    DocumentsNotFoundException,
    GraphRagNotFoundException,
    NaiveRagNotFoundException,
    RagException,
    RagNotReadyForIndexingException,
)
from tables.models.knowledge_models import (
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    NaiveRag,
)
from tables.services.run_admission import RunKind, RunSubject, assert_run_admitted


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
    def validate_and_prepare_indexing(rag_id: int, rag_type: str, org_id: int) -> dict[str, Any]:
        """
        Validates RAG configuration and prepares data for indexing.

        Indexing calls the embedder, and a GraphRAG's LLM, as a run would, so it is admitted
        like one before the caller resolves any of their keys.

        Args:
            rag_id: The primary key of the specific RAG implementation. The caller has
                already checked that it belongs to `org_id`.
            rag_type: The type of RAG ("naive" or "graph")
            org_id: The organization the indexing runs in.

        Returns:
            Dict containing:
                - rag_id: int
                - rag_type: str
                - collection_id: int
                - base_rag_type_id: int
                - embedder_id: int, the EmbeddingConfig the indexing calls
                - llm_id: int | None, the LLMConfig a GraphRAG indexing calls
                - the API key secret ids and extra headers of both

        Raises:
            RunAdmissionRefusedError: The embedder or the LLM may not be called now.
        """
        if rag_type == "naive":
            indexing_data = IndexingService._prepare_naive_rag_indexing(rag_id)
        elif rag_type == "graph":
            indexing_data = IndexingService._prepare_graph_rag_indexing(rag_id)
        else:
            raise RagException(f"Unknown rag_type: {rag_type}")
        assert_run_admitted(
            RunSubject(RunKind.EMBEDDING_CONFIG, indexing_data["embedder_id"], org_id)
        )
        if indexing_data["llm_id"] is not None:
            assert_run_admitted(RunSubject(RunKind.LLM_CONFIG, indexing_data["llm_id"], org_id))
        return indexing_data

    @staticmethod
    def _prepare_naive_rag_indexing(naive_rag_id: int) -> dict[str, Any]:
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
                "base_rag_type",
                "base_rag_type__source_collection",
                "embedder__model__embedding_provider",
            ).get(naive_rag_id=naive_rag_id)
        except NaiveRag.DoesNotExist as e:
            raise NaiveRagNotFoundException(naive_rag_id) from e

        # Get related objects
        base_rag_type = naive_rag.base_rag_type
        collection = base_rag_type.source_collection

        # Validate collection exists
        if not collection:
            raise CollectionNotFoundException(
                f"Collection not found for BaseRagType {base_rag_type.rag_type_id}"
            )

        # Validate collection has documents
        document_count = DocumentMetadata.objects.filter(source_collection=collection).count()

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
            "embedder_id": naive_rag.embedder_id,
            "llm_id": None,
            "embedder_api_key_secret_id": naive_rag.embedder.api_key_secret_id,
            "llm_api_key_secret_id": None,
            "embedder_extra_headers": naive_rag.embedder.extra_headers,
            "llm_extra_headers": None,
            "embedder_connection": embedding_config_connection(naive_rag.embedder),
            "embedder_parameters": embedding_config_parameters(naive_rag.embedder),
            "llm_connection": None,
            "llm_parameters": None,
        }

    @staticmethod
    def _prepare_graph_rag_indexing(graph_rag_id: int) -> dict[str, Any]:
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
                "embedder__model__embedding_provider",
                "llm__model__llm_provider",
                "index_config",
            ).get(graph_rag_id=graph_rag_id)
        except GraphRag.DoesNotExist as e:
            raise GraphRagNotFoundException(graph_rag_id) from e

        # Get related objects
        base_rag_type = graph_rag.base_rag_type
        collection = base_rag_type.source_collection

        # Validate collection exists
        if not collection:
            raise CollectionNotFoundException(
                f"Collection not found for BaseRagType {base_rag_type.rag_type_id}"
            )

        # Validate GraphRag has documents linked
        document_count = GraphRagDocument.objects.filter(graph_rag=graph_rag).count()

        if document_count == 0:
            raise RagNotReadyForIndexingException(
                f"GraphRag {graph_rag_id} has no documents. Please add documents before indexing."
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
            "embedder_id": graph_rag.embedder_id,
            "llm_id": graph_rag.llm_id,
            "embedder_api_key_secret_id": graph_rag.embedder.api_key_secret_id,
            "llm_api_key_secret_id": graph_rag.llm.api_key_secret_id,
            "embedder_extra_headers": graph_rag.embedder.extra_headers,
            "llm_extra_headers": graph_rag.llm.extra_headers,
            "embedder_connection": embedding_config_connection(graph_rag.embedder),
            "embedder_parameters": embedding_config_parameters(graph_rag.embedder),
            "llm_connection": llm_config_connection(graph_rag.llm),
            "llm_parameters": llm_config_parameters(graph_rag.llm),
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
            except NaiveRag.DoesNotExist as e:
                raise NaiveRagNotFoundException(rag_id) from e
        elif rag_type == "graph":
            try:
                graph_rag = GraphRag.objects.get(graph_rag_id=rag_id)
                return graph_rag.rag_status
            except GraphRag.DoesNotExist as e:
                raise GraphRagNotFoundException(rag_id) from e
        else:
            raise RagException(f"Unknown rag_type: {rag_type}")
