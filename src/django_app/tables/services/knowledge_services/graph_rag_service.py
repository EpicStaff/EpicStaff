from typing import List, Dict, Any, Optional
from django.db import transaction
from loguru import logger

from tables.models.knowledge_models import (
    SourceCollection,
    BaseRagType,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    GraphRagInputFileType,
    GraphRagChunkStrategyType,
)
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.exceptions import (
    GraphRagNotFoundException,
    EmbedderNotFoundException,
    LLMConfigNotFoundException,
    CollectionNotFoundException,
    InvalidGraphRagParametersException,
    GraphRagDocumentNotFoundException,
)
from tables.constants.knowledge_constants import (
    GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
    GRAPHRAG_DEFAULT_CHUNK_SIZE,
    GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
    GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
    GRAPHRAG_DEFAULT_ENTITY_TYPES,
    GRAPHRAG_DEFAULT_MAX_GLEANINGS,
    GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
    GRAPHRAG_MIN_CHUNK_SIZE,
    GRAPHRAG_MAX_CHUNK_SIZE,
    GRAPHRAG_MIN_CHUNK_OVERLAP,
    GRAPHRAG_MAX_CHUNK_OVERLAP,
    GRAPHRAG_MIN_MAX_GLEANINGS,
    GRAPHRAG_MAX_MAX_GLEANINGS,
    GRAPHRAG_MIN_MAX_CLUSTER_SIZE,
    GRAPHRAG_MAX_MAX_CLUSTER_SIZE,
)


class GraphRagService:
    """
    Service for GraphRag operations.

    Handles:
    - Creating GraphRag with default index configuration
    - Managing index configuration (single update for all nested configs)
    - Managing documents in GraphRag
    - Deleting GraphRag
    """

    @staticmethod
    def _get_collection(collection_id: int) -> SourceCollection:
        """Get collection by ID."""
        try:
            return SourceCollection.objects.get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

    @staticmethod
    def _get_embedder(embedder_id: int) -> EmbeddingConfig:
        """Get embedder by ID."""
        try:
            return EmbeddingConfig.objects.get(pk=embedder_id)
        except EmbeddingConfig.DoesNotExist:
            raise EmbedderNotFoundException(embedder_id)

    @staticmethod
    def _get_llm_config(llm_id: int) -> LLMConfig:
        """Get LLM config by ID."""
        try:
            return LLMConfig.objects.get(pk=llm_id)
        except LLMConfig.DoesNotExist:
            raise LLMConfigNotFoundException(llm_id)

    @staticmethod
    def get_graph_rag(graph_rag_id: int) -> GraphRag:
        """Get GraphRag by ID with related objects."""
        try:
            return GraphRag.objects.select_related(
                "base_rag_type",
                "base_rag_type__source_collection",
                "embedder",
                "llm",
                "index_config",
            ).get(graph_rag_id=graph_rag_id)
        except GraphRag.DoesNotExist:
            raise GraphRagNotFoundException(graph_rag_id)

    @staticmethod
    def get_or_none_graph_rag_by_collection(collection_id: int) -> Optional[GraphRag]:
        """
        Get GraphRag for a collection, or None if doesn't exist.
        """
        try:
            base_rag = BaseRagType.objects.get(
                source_collection_id=collection_id, rag_type=BaseRagType.RagType.GRAPH
            )
            return GraphRag.objects.select_related(
                "embedder",
                "llm",
                "index_config",
            ).get(base_rag_type=base_rag)
        except (BaseRagType.DoesNotExist, GraphRag.DoesNotExist):
            return None

    @staticmethod
    def _create_default_index_config() -> GraphRagIndexConfig:
        """Create default index configuration."""
        index_config = GraphRagIndexConfig.objects.create(
            # Input config
            file_type=GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
            # Chunking config
            chunk_size=GRAPHRAG_DEFAULT_CHUNK_SIZE,
            chunk_overlap=GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
            chunk_strategy=GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
            # Entity extraction config
            entity_types=GRAPHRAG_DEFAULT_ENTITY_TYPES.copy(),
            max_gleanings=GRAPHRAG_DEFAULT_MAX_GLEANINGS,
            # Cluster config
            max_cluster_size=GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
        )

        return index_config

    @staticmethod
    @transaction.atomic
    def create_or_update_graph_rag(
        collection_id: int,
        embedder_id: int,
        llm_id: int,
    ) -> GraphRag:
        """
        Create new GraphRag or update existing one.
        On create: sets up default index config and auto-adds all documents from collection.
        On update: only updates embedder and llm; index config and documents are left untouched.

        Args:
            collection_id: ID of source collection
            embedder_id: ID of embedder to use
            llm_id: ID of LLM config to use (for entity extraction)

        Returns:
            GraphRag instance (new or updated)

        Raises:
            CollectionNotFoundException: If collection not found
            EmbedderNotFoundException: If embedder not found
            LLMConfigNotFoundException: If LLM config not found
        """
        # Validate collection exists
        collection = GraphRagService._get_collection(collection_id)

        # Validate embedder exists
        embedder = GraphRagService._get_embedder(embedder_id)

        # Validate LLM config exists
        llm_config = GraphRagService._get_llm_config(llm_id)

        # Check if GraphRag already exists for this collection
        existing_graph_rag = GraphRagService.get_or_none_graph_rag_by_collection(
            collection_id
        )

        if existing_graph_rag:
            # Update existing GraphRag
            existing_graph_rag.embedder = embedder
            existing_graph_rag.llm = llm_config
            existing_graph_rag.save(update_fields=["embedder", "llm"])

            logger.info(
                f"Updated GraphRag {existing_graph_rag.graph_rag_id} "
                f"for collection {collection_id}"
            )

            return existing_graph_rag

        # Create default index config
        index_config = GraphRagService._create_default_index_config()

        # Create BaseRagType
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )

        # Create GraphRag
        graph_rag = GraphRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedder,
            llm=llm_config,
            index_config=index_config,
            rag_status=GraphRag.GraphRagStatus.NEW,
        )

        # Auto-add ALL documents from collection
        all_documents = DocumentMetadata.objects.filter(
            source_collection_id=collection_id
        )
        for document in all_documents:
            GraphRagDocument.objects.create(graph_rag=graph_rag, document=document)

        doc_count = all_documents.count()

        logger.info(
            f"Created GraphRag {graph_rag.graph_rag_id} "
            f"for collection {collection_id} with {doc_count} documents"
        )

        return graph_rag

    @staticmethod
    def _validate_index_config_params(
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunk_strategy: Optional[str] = None,
        entity_types: Optional[List[str]] = None,
        max_gleanings: Optional[int] = None,
        max_cluster_size: Optional[int] = None,
    ) -> None:
        """
        Validate index config parameters.

        Raises:
            InvalidGraphRagParametersException: If parameters are invalid
        """
        errors = []

        if chunk_size is not None:
            if (
                chunk_size < GRAPHRAG_MIN_CHUNK_SIZE
                or chunk_size > GRAPHRAG_MAX_CHUNK_SIZE
            ):
                errors.append(
                    f"chunk_size must be between {GRAPHRAG_MIN_CHUNK_SIZE} and {GRAPHRAG_MAX_CHUNK_SIZE}"
                )

        if chunk_overlap is not None:
            if (
                chunk_overlap < GRAPHRAG_MIN_CHUNK_OVERLAP
                or chunk_overlap > GRAPHRAG_MAX_CHUNK_OVERLAP
            ):
                errors.append(
                    f"chunk_overlap must be between {GRAPHRAG_MIN_CHUNK_OVERLAP} and {GRAPHRAG_MAX_CHUNK_OVERLAP}"
                )

        if chunk_size is not None and chunk_overlap is not None:
            if chunk_overlap >= chunk_size:
                errors.append("chunk_overlap must be less than chunk_size")

        if chunk_strategy is not None:
            valid_strategies = [
                choice[0] for choice in GraphRagChunkStrategyType.choices
            ]
            if chunk_strategy not in valid_strategies:
                errors.append(
                    f"chunk_strategy must be one of: {', '.join(valid_strategies)}"
                )

        if entity_types is not None:
            if not isinstance(entity_types, list):
                errors.append("entity_types must be a list")
            elif len(entity_types) == 0:
                errors.append("entity_types cannot be empty")

        if max_gleanings is not None:
            if (
                max_gleanings < GRAPHRAG_MIN_MAX_GLEANINGS
                or max_gleanings > GRAPHRAG_MAX_MAX_GLEANINGS
            ):
                errors.append(
                    f"max_gleanings must be between {GRAPHRAG_MIN_MAX_GLEANINGS} and {GRAPHRAG_MAX_MAX_GLEANINGS}"
                )

        if max_cluster_size is not None:
            if (
                max_cluster_size < GRAPHRAG_MIN_MAX_CLUSTER_SIZE
                or max_cluster_size > GRAPHRAG_MAX_MAX_CLUSTER_SIZE
            ):
                errors.append(
                    f"max_cluster_size must be between {GRAPHRAG_MIN_MAX_CLUSTER_SIZE} and {GRAPHRAG_MAX_MAX_CLUSTER_SIZE}"
                )

        if errors:
            raise InvalidGraphRagParametersException("; ".join(errors))

    @staticmethod
    @transaction.atomic
    def update_index_config(
        graph_rag_id: int,
        # Input config
        file_type: Optional[str] = None,
        # Chunking config
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunk_strategy: Optional[str] = None,
        # Extract graph config
        entity_types: Optional[List[str]] = None,
        max_gleanings: Optional[int] = None,
        # Cluster graph config
        max_cluster_size: Optional[int] = None,
    ) -> GraphRag:
        """
        Update index configuration for GraphRag.

        Args:
            graph_rag_id: ID of GraphRag
            file_type: Input file type (csv, text, json)
            chunk_size: Chunk size
            chunk_overlap: Chunk overlap
            chunk_strategy: Chunking strategy (tokens, sentence)
            entity_types: List of entity types to extract
            max_gleanings: Maximum gleanings for entity extraction
            max_cluster_size: Maximum cluster size

        Returns:
            Updated GraphRag instance

        Raises:
            GraphRagNotFoundException: If GraphRag not found
            InvalidGraphRagParametersException: If parameters are invalid
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)

        if not graph_rag.index_config:
            raise InvalidGraphRagParametersException(
                "GraphRag has no index configuration"
            )

        index_config = graph_rag.index_config

        # Get current values for validation
        final_chunk_size = (
            chunk_size if chunk_size is not None else index_config.chunk_size
        )
        final_chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else index_config.chunk_overlap
        )

        # Validate parameters
        GraphRagService._validate_index_config_params(
            chunk_size=final_chunk_size,
            chunk_overlap=final_chunk_overlap,
            chunk_strategy=chunk_strategy,
            entity_types=entity_types,
            max_gleanings=max_gleanings,
            max_cluster_size=max_cluster_size,
        )

        # Validate file_type if provided
        if file_type is not None:
            valid_file_types = [choice[0] for choice in GraphRagInputFileType.choices]
            if file_type not in valid_file_types:
                raise InvalidGraphRagParametersException(
                    f"file_type must be one of: {', '.join(valid_file_types)}"
                )

        # Build update dict
        updates = {}
        if file_type is not None:
            updates["file_type"] = file_type
        if chunk_size is not None:
            updates["chunk_size"] = chunk_size
        if chunk_overlap is not None:
            updates["chunk_overlap"] = chunk_overlap
        if chunk_strategy is not None:
            updates["chunk_strategy"] = chunk_strategy
        if entity_types is not None:
            updates["entity_types"] = entity_types
        if max_gleanings is not None:
            updates["max_gleanings"] = max_gleanings
        if max_cluster_size is not None:
            updates["max_cluster_size"] = max_cluster_size

        # Apply updates
        for field, value in updates.items():
            setattr(index_config, field, value)

        if updates:
            index_config.save(update_fields=list(updates.keys()))

        logger.info(f"Updated index config for GraphRag {graph_rag_id}")

        return GraphRagService.get_graph_rag(graph_rag_id)

    @staticmethod
    @transaction.atomic
    def remove_documents_from_graph_rag(
        graph_rag_id: int, document_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Remove documents from GraphRag.

        Args:
            graph_rag_id: ID of GraphRag
            document_ids: List of document IDs to remove

        Returns:
            dict with removal info
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)

        # Get links to delete
        links = GraphRagDocument.objects.filter(
            graph_rag=graph_rag, document_id__in=document_ids
        )

        deleted_ids = list(links.values_list("document_id", flat=True))
        deleted_count = links.count()

        links.delete()

        logger.info(f"Removed {deleted_count} documents from GraphRag {graph_rag_id}")

        return {
            "removed_count": deleted_count,
            "removed_document_ids": deleted_ids,
        }

    @staticmethod
    @transaction.atomic
    def delete_document(graph_rag_id: int, document_id: int) -> Dict[str, Any]:
        """
        Remove a single document from GraphRag.

        Args:
            graph_rag_id: ID of GraphRag
            document_id: ID of document to remove

        Returns:
            dict with removal info
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)

        try:
            link = GraphRagDocument.objects.get(
                graph_rag=graph_rag, document_id=document_id
            )
        except GraphRagDocument.DoesNotExist:
            raise GraphRagDocumentNotFoundException(document_id, graph_rag_id)

        link.delete()

        logger.info(f"Removed document {document_id} from GraphRag {graph_rag_id}")

        return {
            "graph_rag_id": graph_rag_id,
            "document_id": document_id,
        }

    @staticmethod
    def get_documents_for_graph_rag(graph_rag_id: int) -> List[DocumentMetadata]:
        """
        Get all documents linked to GraphRag.

        Args:
            graph_rag_id: ID of GraphRag

        Returns:
            List of DocumentMetadata
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)

        document_ids = GraphRagDocument.objects.filter(graph_rag=graph_rag).values_list(
            "document_id", flat=True
        )

        return list(
            DocumentMetadata.objects.filter(document_id__in=document_ids).order_by(
                "file_name"
            )
        )

    @staticmethod
    @transaction.atomic
    def init_documents_from_collection(graph_rag_id: int) -> Dict[str, Any]:
        """
        Re-initialize GraphRag with all documents from collection.
        Adds documents that are not already linked (useful after accidental deletion).

        Args:
            graph_rag_id: ID of GraphRag

        Returns:
            dict with initialization info
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)
        collection_id = graph_rag.base_rag_type.source_collection_id

        # Get all documents in collection
        all_documents = DocumentMetadata.objects.filter(
            source_collection_id=collection_id
        )

        if not all_documents.exists():
            logger.info(
                f"No documents found in collection {collection_id} "
                f"for GraphRag {graph_rag_id}"
            )
            return {
                "added_count": 0,
                "already_linked_count": 0,
                "added_documents": [],
            }

        # Get already linked document IDs
        existing_doc_ids = set(
            GraphRagDocument.objects.filter(graph_rag=graph_rag).values_list(
                "document_id", flat=True
            )
        )

        # Filter documents that need to be added
        documents_to_add = all_documents.exclude(document_id__in=existing_doc_ids)

        # Create links for new documents
        added_documents = []
        for document in documents_to_add:
            link = GraphRagDocument.objects.create(
                graph_rag=graph_rag, document=document
            )
            added_documents.append(
                {
                    "graph_rag_document_id": link.graph_rag_document_id,
                    "document_id": document.document_id,
                    "file_name": document.file_name,
                }
            )

        logger.info(
            f"Initialized {len(added_documents)} documents for GraphRag {graph_rag_id}. "
            f"Already linked: {len(existing_doc_ids)}"
        )

        return {
            "added_count": len(added_documents),
            "already_linked_count": len(existing_doc_ids),
            "added_documents": added_documents,
        }

    @staticmethod
    @transaction.atomic
    def delete_graph_rag(graph_rag_id: int) -> Dict[str, Any]:
        """
        Delete GraphRag and its configurations.

        Args:
            graph_rag_id: ID of GraphRag to delete

        Returns:
            dict with deletion info
        """
        graph_rag = GraphRagService.get_graph_rag(graph_rag_id)
        base_rag_type = graph_rag.base_rag_type
        collection_id = base_rag_type.source_collection_id
        index_config = graph_rag.index_config

        # Count documents before deletion
        doc_count = GraphRagDocument.objects.filter(graph_rag=graph_rag).count()

        # Delete index config
        if index_config:
            index_config.delete()

        # Delete base_rag_type (cascades to GraphRag and GraphRagDocument)
        base_rag_type.delete()

        logger.info(
            f"Deleted GraphRag {graph_rag_id} for collection {collection_id} "
            f"with {doc_count} documents"
        )

        return {
            "graph_rag_id": graph_rag_id,
            "collection_id": collection_id,
            "deleted_document_count": doc_count,
        }
