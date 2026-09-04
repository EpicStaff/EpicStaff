from typing import Dict, Any, List, Literal
from django.db import transaction, models
from django.db.models import Prefetch, Count, Avg
from loguru import logger

from src.shared.enums.knowledge_new import RAGStrategy
from src.shared.models.search_config_suggestion import SuggestedCollectionMetrics
from tables.clients import KnowledgeClient
from tables.clients.errors import (
    ClientBadGatewayError,
    ClientNotAvailableError,
    ClientTimeoutError,
)
from tables.models import SourceCollection, DocumentMetadata, DocumentContent
from tables.models.knowledge_models import BaseRagType, NaiveRag, GraphRag
from tables.models.knowledge_models.naive_rag_models import (
    NaiveRagChunk,
    NaiveRagDocumentConfig,
)
from tables.exceptions import (
    CollectionNotFoundException,
    NoGraphRagForCollectionException,
    GraphRagIndexNotReadyException,
    GraphRagMetricsUnavailableException,
    NoNaiveRagForCollectionException,
    NaiveRagIndexNotReadyException,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService


class CollectionManagementService:
    """
    Service for handling source collection operations.

    Responsibilities:
    - Create, update, delete collections
    - Copy collections (without duplicating content)
    - Clean up unreferenced content
    """

    @staticmethod
    def get_collection(collection_id: int) -> SourceCollection:
        """
        Get source collection by ID.

        Args:
            collection_id: ID of the source collection

        Returns:
            SourceCollection: The source collection instance

        Raises:
            CollectionNotFoundException: If collection not found
        """
        try:
            return SourceCollection.objects.get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

    @staticmethod
    def get_collection_metrics(
        collection_id: int,
        rag_type: Literal["naive", "graph"],
    ) -> SuggestedCollectionMetrics:
        CollectionManagementService.get_collection(collection_id)
        if rag_type == "naive":
            return CollectionManagementService._get_naive_metrics(collection_id)
        return CollectionManagementService._get_graph_metrics(collection_id)

    @staticmethod
    def _get_naive_metrics(collection_id: int) -> SuggestedCollectionMetrics:
        naive_rag = NaiveRagService.get_or_none_naive_rag_by_collection(collection_id)
        if naive_rag is None:
            raise NoNaiveRagForCollectionException(collection_id)
        if naive_rag.rag_status != NaiveRag.NaiveRagStatus.COMPLETED:
            raise NaiveRagIndexNotReadyException(collection_id)
        chunk_agg = NaiveRagChunk.objects.filter(
            naive_rag_document_config__naive_rag__base_rag_type__source_collection_id=collection_id,
        ).aggregate(total=Count("chunk_id"), avg=Avg("token_count"))
        total_documents = NaiveRagDocumentConfig.objects.filter(
            naive_rag__base_rag_type__source_collection_id=collection_id,
        ).count()
        return SuggestedCollectionMetrics(
            total_documents=total_documents,
            total_chunks=chunk_agg["total"] or 0,
            avg_chunk_size=float(chunk_agg["avg"] or 0),
        )

    @staticmethod
    def _get_graph_metrics(collection_id: int) -> SuggestedCollectionMetrics:
        graph_rag = GraphRagService.get_or_none_graph_rag_by_collection(collection_id)
        if graph_rag is None:
            raise NoGraphRagForCollectionException(collection_id)
        if graph_rag.rag_status != GraphRag.GraphRagStatus.COMPLETED:
            raise GraphRagIndexNotReadyException(collection_id)
        try:
            with KnowledgeClient() as client:
                metrics = client.metrics(RAGStrategy.GRAPH, graph_rag.graph_rag_id)
        except (
            ClientNotAvailableError,
            ClientTimeoutError,
            ClientBadGatewayError,
        ) as e:
            raise GraphRagMetricsUnavailableException(collection_id) from e
        return SuggestedCollectionMetrics(
            total_documents=graph_rag.graph_rag_documents.count(),
            total_chunks=metrics["total_chunks"],
            avg_chunk_size=metrics["avg_chunk_size"],
        )

    @staticmethod
    @transaction.atomic
    def create_collection(
        collection_name: str = None,
        description: str = "",
        user_id: str = None,
        collection_origin: str = None,
        org_id: int = None,
    ) -> SourceCollection:
        """
        Create a new empty collection.

        Args:
            collection_name: Name for collection (auto-generated if None)
            description: LLM-facing context appended to generated knowledge tool
                descriptions (defaults to blank)
            user_id: User ID (defaults to "dummy_user")
            collection_origin: Origin of collection (defaults to USER)
            org_id: Owning organization id (required — collection.org is NOT NULL)

        Returns:
            SourceCollection: Created collection
        """
        collection = SourceCollection.objects.create(
            collection_name=collection_name or "Untitled Collection",
            description=description or "",
            user_id=user_id or "dummy_user",
            collection_origin=collection_origin
            or SourceCollection.SourceCollectionOrigin.USER,
            org_id=org_id,
        )

        logger.info(
            f"Created collection '{collection.collection_name}' (ID: {collection.collection_id})"
        )

        return collection

    @staticmethod
    @transaction.atomic
    def update_collection(
        collection_id: int,
        collection_name: str = None,
        description: str = None,
    ) -> SourceCollection:
        """
        Update collection name and/or description.

        Args:
            collection_id: ID of collection to update
            collection_name: New collection name (unchanged if None)
            description: New description (unchanged if None)

        Returns:
            SourceCollection: Updated collection

        Raises:
            CollectionNotFoundException: If collection not found
        """
        collection = CollectionManagementService.get_collection(collection_id)

        update_fields = []

        if collection_name is not None:
            collection.collection_name = collection_name
            update_fields.append("collection_name")

        if description is not None:
            collection.description = description
            update_fields.append("description")

        if update_fields:
            collection.save()

        logger.info(
            f"Updated collection {collection_id} fields: {update_fields or 'none'}"
        )

        return collection

    @staticmethod
    @transaction.atomic
    def delete_collection(collection_id: int) -> Dict[str, Any]:
        """
        Delete collection and all its documents.
        Cleans up unreferenced DocumentContent.

        Args:
            collection_id: ID of collection to delete

        Returns:
            dict: Deletion summary

        Raises:
            CollectionNotFoundException: If collection not found
        """
        collection = CollectionManagementService.get_collection(collection_id)

        collection_name = collection.collection_name

        # Get all document IDs in this collection
        document_ids = list(collection.documents.values_list("document_id", flat=True))

        # Collect content IDs before deletion
        content_ids = list(
            collection.documents.exclude(document_content__isnull=True).values_list(
                "document_content_id", flat=True
            )
        )

        # Delete collection (cascades to DocumentMetadata)
        collection.delete()

        # Clean up unreferenced content
        unreferenced_count = 0
        if content_ids:
            unreferenced_content = (
                DocumentContent.objects.filter(id__in=content_ids)
                .annotate(ref_count=models.Count("metadata_records"))
                .filter(ref_count=0)
            )

            unreferenced_count = unreferenced_content.count()
            if unreferenced_count > 0:
                unreferenced_content.delete()
                logger.info(
                    f"Deleted {unreferenced_count} unreferenced content records"
                )

        logger.info(
            f"Deleted collection '{collection_name}' (ID: {collection_id}) "
            f"with {len(document_ids)} documents"
        )

        return {
            "collection_id": collection_id,
            "collection_name": collection_name,
            "deleted_documents": len(document_ids),
            "deleted_content": unreferenced_count,
        }

    @staticmethod
    @transaction.atomic
    def bulk_delete_collections(collection_ids: list[int]) -> Dict[str, Any]:
        """
        Delete multiple collections in a single transaction.
        Cleans up unreferenced DocumentContent.

        Args:
            collection_ids: List of collection IDs to delete

        Returns:
            dict: Deletion summary
        """
        if not collection_ids:
            return {
                "deleted_count": 0,
                "collections": [],
                "deleted_documents": 0,
                "deleted_content": 0,
            }

        # Fetch all collections
        collections = SourceCollection.objects.filter(collection_id__in=collection_ids)

        found_ids = [col.collection_id for col in collections]
        missing_ids = list(set(collection_ids) - set(found_ids))

        if missing_ids:
            logger.warning(f"Cannot find collections with IDs: {missing_ids}")

        # Store info before deletion
        deleted_info = [
            {
                "collection_id": col.collection_id,
                "collection_name": col.collection_name,
            }
            for col in collections
        ]

        # Count documents across all collections
        total_documents = DocumentMetadata.objects.filter(
            source_collection__in=collections
        ).count()

        # Collect content IDs before deletion
        content_ids = list(
            DocumentMetadata.objects.filter(source_collection__in=collections)
            .exclude(document_content__isnull=True)
            .values_list("document_content_id", flat=True)
        )

        # Delete collections (cascades to DocumentMetadata)
        deleted_count, _ = collections.delete()

        # Clean up unreferenced content
        dangling_count = 0
        if content_ids:
            dangling_content = (
                DocumentContent.objects.filter(id__in=content_ids)
                .annotate(ref_count=models.Count("metadata_records"))
                .filter(ref_count=0)
            )

            dangling_count = dangling_content.count()
            if dangling_count > 0:
                dangling_content.delete()
                logger.info(f"Deleted {dangling_count} unreferenced content records")

        logger.info(
            f"Bulk deleted {deleted_count} collections with "
            f"{total_documents} documents and {dangling_count} unreferenced content"
        )

        return {
            "deleted_count": deleted_count,
            "collections": deleted_info,
            "deleted_documents": total_documents,
            "deleted_content": dangling_count,
        }

    @staticmethod
    @transaction.atomic
    def copy_collection(
        source_collection_id: int,
        new_collection_name: str = None,
        org_id: int = None,
    ) -> SourceCollection:
        """
        Copy a collection without duplicating binary content.
        Creates new DocumentMetadata pointing to same DocumentContent.

        Args:
            source_collection_id: ID of collection to copy
            new_collection_name: Name for new collection (auto-generated if None)
            user_id: User ID for new collection (uses source if None)

        Returns:
            SourceCollection: New collection instance

        Raises:
            CollectionNotFoundException: If source collection not found
        """
        # Get source collection
        source_collection = CollectionManagementService.get_collection(
            source_collection_id
        )

        # Create new collection (name auto-deduplicated by model.save())
        new_collection = SourceCollection.objects.create(
            collection_name=new_collection_name
            or f"{source_collection.collection_name} (Copy)",
            description=source_collection.description,
            org_id=org_id,
        )

        # Get source documents with content
        source_documents = DocumentMetadata.objects.filter(
            source_collection=source_collection
        ).select_related("document_content")

        if source_documents:
            new_collection.status = SourceCollection.SourceCollectionStatus.UPLOADING
            new_collection.save(update_fields=["status", "updated_at"])

        if not source_documents.exists():
            logger.info(
                f"Copied empty collection {source_collection_id} to {new_collection.collection_id}"
            )
            return new_collection

        # Copy metadata pointing to same content
        for source_doc in source_documents:
            DocumentMetadata.objects.create(
                source_collection=new_collection,
                file_name=source_doc.file_name,
                file_type=source_doc.file_type,
                file_size=source_doc.file_size,
                document_content=source_doc.document_content,
            )

        logger.info(
            f"Copied collection {source_collection_id} to {new_collection.collection_id} "
            f"with {source_documents.count()} documents"
        )

        return new_collection

    @staticmethod
    def rag_configurations_prefetch():
        """Prefetch chain for the full RAG summary; spread into
        ``queryset.prefetch_related(*...())``.

        Loads rag_types with their naive_rags/graph_rags and annotates the count
        fields (document_configs/chunks/embeddings/documents) in SQL, so the
        summary builder never loads those rows.
        """
        naive_rag_qs = NaiveRag.objects.select_related("embedder").annotate(
            document_configs_count=Count("naive_rag_configs", distinct=True),
            chunks_count=Count("naive_rag_configs__chunks", distinct=True),
            embeddings_count=Count("naive_rag_configs__embeddings", distinct=True),
        )
        graph_rag_qs = GraphRag.objects.select_related("embedder", "llm").annotate(
            documents_count=Count("graph_rag_documents")
        )
        return (
            "rag_types",
            Prefetch("rag_types__naive_rags", queryset=naive_rag_qs),
            Prefetch("rag_types__graph_rags", queryset=graph_rag_qs),
        )

    @staticmethod
    def get_rag_configurations(collection_id: int) -> List[Dict[str, Any]]:
        """
        Get all RAG configurations for a collection.

        This method aggregates all RAG implementations (NaiveRag, GraphRag, etc.)
        for a given collection, returning summary data for each.

        Args:
            collection_id: ID of the source collection

        Returns:
            List[Dict]: List of RAG configuration summaries, each containing:
                - rag_id: ID of the specific RAG implementation
                - rag_type: Type of RAG ("naive", "graph", etc.)
                - status
                - is_ready_for_indexing
                - embedder_name
                - embedder_id
                - document_configs_count
                - chunks_count
                - embeddings_count
                - created_at
                - updated_at
        """
        # Validate collection exists
        try:
            collection = SourceCollection.objects.prefetch_related(
                *CollectionManagementService.rag_configurations_prefetch()
            ).get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

        rag_configurations = []
        for base_rag_type in collection.rag_types.all():
            for naive_rag in base_rag_type.naive_rags.all():
                rag_configurations.append(
                    CollectionManagementService._get_naive_rag_summary(naive_rag)
                )
            for graph_rag in base_rag_type.graph_rags.all():
                rag_configurations.append(
                    CollectionManagementService._get_graph_rag_summary(graph_rag)
                )
        return rag_configurations

    @staticmethod
    def _get_naive_rag_summary(naive_rag: NaiveRag) -> Dict[str, Any]:
        """
        Get summary data for a NaiveRag configuration.

        Args:
            naive_rag: NaiveRag instance with the count annotations and
                ``embedder`` prefetched by the caller's queryset
                (``rag_configurations_prefetch`` or the detail serializer's
                direct query).

        Returns:
            Dict with NaiveRag summary
        """
        document_configs_count = naive_rag.document_configs_count
        chunks_count = naive_rag.chunks_count
        embeddings_count = naive_rag.embeddings_count

        # Determine if ready for indexing
        is_ready_for_indexing = (
            naive_rag.embedder is not None and document_configs_count > 0
        )

        return {
            "rag_id": naive_rag.naive_rag_id,
            "rag_type": "naive",
            "status": naive_rag.rag_status,
            "outdated_reasons": naive_rag.outdated_reasons,
            "is_ready_for_indexing": is_ready_for_indexing,
            "embedder_name": (
                naive_rag.embedder.custom_name if naive_rag.embedder else None
            ),
            "embedder_id": naive_rag.embedder.id if naive_rag.embedder else None,
            "document_configs_count": document_configs_count,
            "chunks_count": chunks_count,
            "embeddings_count": embeddings_count,
            "indexing_document_config_ids": naive_rag.indexing_document_config_ids,
            "created_at": naive_rag.created_at,
            "updated_at": naive_rag.updated_at,
        }

    @staticmethod
    def _get_graph_rag_summary(graph_rag: GraphRag) -> Dict[str, Any]:
        """
        Get summary data for a GraphRag configuration.

        Args:
            graph_rag: GraphRag instance with ``documents_count`` and the
                ``embedder``/``llm`` relations provided by the caller's queryset
                (``rag_configurations_prefetch`` or the detail serializer's
                direct query).

        Returns:
            Dict with GraphRag summary
        """
        # documents_count is annotated on the queryset by the caller
        documents_count = graph_rag.documents_count

        # Determine if ready for indexing
        is_ready_for_indexing = (
            graph_rag.embedder is not None
            and graph_rag.llm is not None
            and documents_count > 0
        )

        return {
            "rag_id": graph_rag.graph_rag_id,
            "rag_type": "graph",
            "status": graph_rag.rag_status,
            "outdated_reasons": graph_rag.outdated_reasons,
            "is_ready_for_indexing": is_ready_for_indexing,
            "embedder_name": (
                graph_rag.embedder.custom_name if graph_rag.embedder else None
            ),
            "embedder_id": graph_rag.embedder.id if graph_rag.embedder else None,
            "llm_name": graph_rag.llm.custom_name if graph_rag.llm else None,
            "llm_id": graph_rag.llm.id if graph_rag.llm else None,
            "documents_count": documents_count,
            "processing_document_ids": list(graph_rag.indexing_document_config_ids),
            "message": graph_rag.error_message,
            "indexed_at": graph_rag.indexed_at,
            "created_at": graph_rag.created_at,
            "updated_at": graph_rag.updated_at,
        }
