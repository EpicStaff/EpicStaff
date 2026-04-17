from typing import Dict, Any, Optional, List
from django.db import transaction, models
from loguru import logger

from tables.models import SourceCollection, DocumentMetadata, DocumentContent
from tables.models.knowledge_models import BaseRagType, NaiveRag, GraphRag
from tables.exceptions import CollectionNotFoundException


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
    @transaction.atomic
    def create_collection(
        collection_name: str = None, user_id: str = None, collection_origin: str = None
    ) -> SourceCollection:
        """
        Create a new empty collection.

        Args:
            collection_name: Name for collection (auto-generated if None)
            user_id: User ID (defaults to "dummy_user")
            collection_origin: Origin of collection (defaults to USER)

        Returns:
            SourceCollection: Created collection
        """
        collection = SourceCollection.objects.create(
            collection_name=collection_name or "Untitled Collection",
            user_id=user_id or "dummy_user",
            collection_origin=collection_origin
            or SourceCollection.SourceCollectionOrigin.USER,
        )

        logger.info(
            f"Created collection '{collection.collection_name}' (ID: {collection.collection_id})"
        )

        return collection

    @staticmethod
    @transaction.atomic
    def update_collection(collection_id: int, collection_name: str) -> SourceCollection:
        """
        Update collection name.

        Args:
            collection_id: ID of collection to update
            collection_name: New collection name

        Returns:
            SourceCollection: Updated collection

        Raises:
            CollectionNotFoundException: If collection not found
        """
        collection = CollectionManagementService.get_collection(collection_id)
        collection.collection_name = collection_name
        collection.save()

        logger.info(f"Updated collection {collection_id} name to '{collection_name}'")

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
            or f"{source_collection.collection_name} (Copy)"
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
            SourceCollection.objects.get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

        rag_configurations = []

        # Get all BaseRagType entries for this collection
        base_rag_types = BaseRagType.objects.filter(
            source_collection_id=collection_id
        ).select_related("source_collection")

        for base_rag_type in base_rag_types:
            if base_rag_type.rag_type == BaseRagType.RagType.NAIVE:
                # Get NaiveRag configuration
                naive_rag_config = CollectionManagementService._get_naive_rag_summary(
                    base_rag_type
                )
                if naive_rag_config:
                    rag_configurations.append(naive_rag_config)

            elif base_rag_type.rag_type == BaseRagType.RagType.GRAPH:
                # Get GraphRag configuration
                graph_rag_config = CollectionManagementService._get_graph_rag_summary(
                    base_rag_type
                )
                if graph_rag_config:
                    rag_configurations.append(graph_rag_config)

        return rag_configurations

    @staticmethod
    def _get_naive_rag_summary(base_rag_type: BaseRagType) -> Optional[Dict[str, Any]]:
        """
        Get summary data for a NaiveRag configuration.

        Args:
            base_rag_type: BaseRagType instance

        Returns:
            Dict with NaiveRag summary or None if not found
        """
        try:
            naive_rag = (
                NaiveRag.objects.select_related("embedder")
                .prefetch_related(
                    "naive_rag_configs",
                    "naive_rag_configs__chunks",
                    "naive_rag_configs__embeddings",
                )
                .get(base_rag_type=base_rag_type)
            )
        except NaiveRag.DoesNotExist:
            return None

        # Count document configs, chunks, and embeddings
        document_configs_count = naive_rag.naive_rag_configs.count()
        chunks_count = sum(
            config.chunks.count() for config in naive_rag.naive_rag_configs.all()
        )
        embeddings_count = sum(
            config.embeddings.count() for config in naive_rag.naive_rag_configs.all()
        )

        # Determine if ready for indexing
        is_ready_for_indexing = (
            naive_rag.embedder is not None and document_configs_count > 0
        )

        return {
            "rag_id": naive_rag.naive_rag_id,
            "rag_type": "naive",
            "status": naive_rag.rag_status,
            "is_ready_for_indexing": is_ready_for_indexing,
            "embedder_name": (
                naive_rag.embedder.custom_name if naive_rag.embedder else None
            ),
            "embedder_id": naive_rag.embedder.id if naive_rag.embedder else None,
            "document_configs_count": document_configs_count,
            "chunks_count": chunks_count,
            "embeddings_count": embeddings_count,
            "created_at": naive_rag.created_at,
            "updated_at": naive_rag.updated_at,
        }

    @staticmethod
    def _get_graph_rag_summary(base_rag_type: BaseRagType) -> Optional[Dict[str, Any]]:
        """
        Get summary data for a GraphRag configuration.

        Args:
            base_rag_type: BaseRagType instance

        Returns:
            Dict with GraphRag summary or None if not found
        """
        try:
            graph_rag = (
                GraphRag.objects.select_related(
                    "embedder",
                    "llm",
                    "index_config",
                )
                .prefetch_related("graph_rag_documents")
                .get(base_rag_type=base_rag_type)
            )
        except GraphRag.DoesNotExist:
            return None

        # Count documents linked to GraphRag
        documents_count = graph_rag.graph_rag_documents.count()

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
            "is_ready_for_indexing": is_ready_for_indexing,
            "embedder_name": (
                graph_rag.embedder.custom_name if graph_rag.embedder else None
            ),
            "embedder_id": graph_rag.embedder.id if graph_rag.embedder else None,
            "llm_name": graph_rag.llm.custom_name if graph_rag.llm else None,
            "llm_id": graph_rag.llm.id if graph_rag.llm else None,
            "documents_count": documents_count,
            "indexed_at": graph_rag.indexed_at,
            "created_at": graph_rag.created_at,
            "updated_at": graph_rag.updated_at,
        }
