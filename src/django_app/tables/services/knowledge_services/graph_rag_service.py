from typing import List, Dict, Any, Optional
from django.db import transaction
from django.db.models import Q, F, OuterRef
from loguru import logger

from tables.models.knowledge_models import (
    SourceCollection,
    BaseRagType,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
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
    DocumentConfigNotFoundException,
    InvalidChunkParametersException,
)
from tables.constants.knowledge_constants import (
    GRAPHRAG_DEFAULT_INPUT_FILE_TYPE,
    GRAPHRAG_DEFAULT_CHUNK_SIZE,
    GRAPHRAG_DEFAULT_CHUNK_OVERLAP,
    GRAPHRAG_DEFAULT_CHUNK_STRATEGY,
    GRAPHRAG_DEFAULT_ENTITY_TYPES,
    GRAPHRAG_DEFAULT_MAX_GLEANINGS,
    GRAPHRAG_DEFAULT_MAX_CLUSTER_SIZE,
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
    def _mark_completed_documents_outdated(graph_rag: GraphRag) -> int:
        return (
            graph_rag.graph_rag_documents
            .filter(status=GraphRagDocument.Status.COMPLETED)
            .update(status=GraphRagDocument.Status.OUTDATED)
        )

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

    @classmethod
    def _create_rag(
        cls,
        collection: SourceCollection,
        embedding_config: EmbeddingConfig,
        llm_config: LLMConfig,
    ) -> GraphRag:
        index_config = cls._create_default_index_config()
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )
        rag = GraphRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            llm=llm_config,
            index_config=index_config,
        )

        all_documents = collection.documents.iterator(chunk_size=100)
        graph_rag_documents = [
            GraphRagDocument(graph_rag=rag, document=d)
            for d in all_documents
        ] # fmt: off
        GraphRagDocument.objects.bulk_create(graph_rag_documents, batch_size=100)

        logger.info(
            f"Created GraphRag {rag.graph_rag_id} "
            f"for collection {collection.collection_id} with {len(graph_rag_documents)} documents."
        )

        return rag


    @classmethod
    def _update_rag(
        cls,
        rag: GraphRag,
        collection: SourceCollection,
        embedding_config: EmbeddingConfig,
        llm_config: LLMConfig,
    ) -> GraphRag:
        updated_fields = set()
        embedding_provider_changed = (
            rag.embedder is None
            or rag.embedder.model.embedding_provider != embedding_config.model.embedding_provider
        )

        if rag.embedder is None or rag.embedder.pk != embedding_config.pk:
            if embedding_provider_changed:
                rag.rag_status = rag.GraphRagStatus.OUTDATED
                rag.add_outdated_reason(
                    'changed_embedding_config',
                    'Embedding config was changed.',
                )
                updated_fields.update(['rag_status', 'outdated_reasons'])
            rag.embedder = embedding_config
            updated_fields.add('embedder')

        if rag.llm is None or rag.llm.pk != llm_config.pk:
            rag.llm = llm_config
            updated_fields.add('llm')

        rag.save(update_fields=updated_fields)

        if embedding_provider_changed:
            (
                rag.graph_rag_documents
                .filter(
                    ~Q(graph_rag_document_id__in=rag.indexing_document_config_ids),
                    status=GraphRagDocument.Status.COMPLETED,
                )
                .update(status=GraphRagDocument.Status.OUTDATED)
            )

        logger.info(f"Updated GraphRag {rag.graph_rag_id} for collection {collection.collection_id}")

        return rag

    @classmethod
    @transaction.atomic
    def create_or_update_graph_rag(
        cls,
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
        collection = cls._get_collection(collection_id)
        embedding_config = cls._get_embedder(embedder_id)
        llm_config = cls._get_llm_config(llm_id)

        rag = cls.get_or_none_graph_rag_by_collection(collection_id)
        if rag:
            rag = cls._update_rag(rag, collection, embedding_config, llm_config)
        else:
            rag = cls._create_rag(collection, embedding_config, llm_config)

        return rag

    @classmethod
    @transaction.atomic
    def update_index_config(
        cls,
        graph_rag_id: int,
        data: dict[str, Any],
    ) -> GraphRag:
        """
        Update index configuration for GraphRag.

        Args:
            graph_rag_id: ID of GraphRag

        Returns:
            Updated GraphRag instance

        Raises:
            GraphRagNotFoundException: If GraphRag not found
            InvalidGraphRagParametersException: If parameters are invalid
        """
        logger.info("start update index config for data: {}", data)

        # TODO: it is unprotected from system changing index config at indexing.

        rag = cls.get_graph_rag(graph_rag_id)
        if not rag.index_config:
            raise InvalidGraphRagParametersException(
                "GraphRag has no index configuration"
            )
        index_config = rag.index_config

        chunk_size = data.get("chunk_size") or index_config.chunk_size
        chunk_overlap = data.get("chunk_overlap") or index_config.chunk_overlap
        if chunk_overlap >= chunk_size:
            reason = "'chunk_overlap' must be less than 'chunk_size'"
            raise InvalidChunkParametersException(
                errors=[{"field": "chunk_overlap", "value": chunk_overlap, "reason": reason}],
            )
        
        updated_fields = set()
        for field, value in data.items():
            old_value = getattr(index_config, field)
            if value is not None and old_value != value:
                setattr(index_config, field, value)
                updated_fields.add(field)

        if updated_fields:
            index_config.save(update_fields=updated_fields)

            completed_documents = (
                rag.graph_rag_documents
                .filter(
                    ~Q(graph_rag_document_id__in=rag.indexing_document_config_ids),
                    status=GraphRagDocument.Status.COMPLETED,
                )
            )
            if completed_documents:
                rag.add_outdated_reason(
                    code="index_config_changed",
                    detail="Index config was changed.",
                )
                rag.rag_status = GraphRag.GraphRagStatus.OUTDATED
                rag.save(update_fields={"outdated_reasons", "rag_status"})
                completed_documents.update(status=GraphRagDocument.Status.OUTDATED)

        logger.info("Updated index config for GraphRag(id={})", graph_rag_id)

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
        rag = GraphRagService.get_graph_rag(graph_rag_id)
        documents = rag.graph_rag_documents.filter(document_id__in=document_ids)

        found_ids = {d.document_id for d in documents}
        missing_ids = set(document_ids) - found_ids
        if missing_ids:
            raise GraphRagDocumentNotFoundException(
                f"Documents not found or don't belong to"
                f" GraphRag {rag.graph_rag_id}: {sorted(missing_ids)}"
            )

        completed_document_deleted = documents.filter(status=GraphRagDocument.Status.COMPLETED).exists()
        deleted_document_ids = list(documents.values_list("document_id", flat=True))
        documents.delete()

        GraphRagService.sync_status_after_document_removal(rag, completed_document_deleted)

        logger.info(
            "Removed {} documents from GraphRag(id={})",
            len(deleted_document_ids),
            graph_rag_id
        )

        return {"removed_count": len(deleted_document_ids), "removed_document_ids": deleted_document_ids}

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
        rag = GraphRagService.get_graph_rag(graph_rag_id)
        document = rag.graph_rag_documents.filter(document_id=document_id).first()
        if document is None:
            raise GraphRagDocumentNotFoundException(
                f"Document {document_id} is not linked to GraphRag {graph_rag_id}"
            )

        was_completed = document.status == GraphRagDocument.Status.COMPLETED
        document.delete()

        GraphRagService.sync_status_after_document_removal(rag, was_completed)

        logger.info(
            "Removed document(id={}) from GraphRag(id={})",
            document_id,
            graph_rag_id,
        )

        return {"graph_rag_id": graph_rag_id, "document_id": document_id}

    @staticmethod
    def sync_status_after_document_removal(rag: GraphRag, indexed_document_deleted: bool) -> None:
        updated_fields = set()
        S = GraphRagDocument.Status
        if indexed_document_deleted:
            # Graph can't excise a single file from the index — treat any indexed
            # deletion as outdating the whole graph.
            rag.graph_rag_documents.filter(status=S.COMPLETED).update(status=S.OUTDATED)
            rag.add_outdated_reason(
                code="indexed_document_deleted",
                detail="Indexed document was deleted.",
            )
            updated_fields.add("outdated_reasons")
        has_outdated = rag.graph_rag_documents.filter(status=S.OUTDATED).exists()
        if not has_outdated and rag.outdated_reasons:
            rag.clear_outdated_reason()
            updated_fields.add("outdated_reasons")
        if rag.update_rag_status():
            updated_fields.add("rag_status")
        if updated_fields:
            rag.save(update_fields=updated_fields)

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
        documents = graph_rag.graph_rag_documents.select_related("document").all()
        return list(documents)

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
