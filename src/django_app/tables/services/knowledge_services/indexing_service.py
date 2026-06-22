from typing import Dict, Any, List, Optional
from django.db import transaction
from django.utils import timezone
from loguru import logger

from tables.models.knowledge_models import (
    NaiveRag,
    NaiveRagDocumentConfig,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    SourceCollection,
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
    def validate_and_prepare_indexing(
        rag_id: int,
        rag_type: str,
        document_config_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Validates RAG configuration and prepares data for indexing.

        Args:
            rag_id: The primary key of the specific RAG implementation
            rag_type: The type of RAG ("naive" or "graph")
            document_config_ids: Optional list of specific config IDs to index.
                If None, all configs for the RAG are resolved (naive only).

        Returns:
            Dict containing rag_id, rag_type, collection_id, base_rag_type_id.
            For naive RAG also contains accepted_config_ids,
            skipped_completed_config_ids, skipped_in_progress_config_ids.
        """
        if rag_type == "naive":
            return IndexingService._prepare_naive_rag_indexing(
                rag_id=rag_id, document_config_ids=document_config_ids
            )
        elif rag_type == "graph":
            return IndexingService._prepare_graph_rag_indexing(rag_id)
        else:
            raise RagException(f"Unknown rag_type: {rag_type}")

    @staticmethod
    def _prepare_naive_rag_indexing(
        naive_rag_id: int,
        document_config_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Validates and prepares NaiveRag for indexing.

        Partitions document configs into three groups:
        - accepted: configs whose params differ from the snapshot → worker will re-index
        - skipped_completed: configs whose live params already match the indexed snapshot
          (flipped to COMPLETED here, no worker dispatch needed)
        - skipped_in_progress: configs with an active worker running (left untouched)

        Accepted configs are bulk-updated to INDEXING status before returning,
        so the worker sees them ready. rag_status is recomputed if any config changed.

        Args:
            naive_rag_id: The NaiveRag primary key
            document_config_ids: Optional list of specific config IDs to index.
                If None, all configs for the RAG are resolved.

        Returns:
            Dict with rag_id, rag_type, collection_id, base_rag_type_id,
            accepted_config_ids, skipped_completed_config_ids,
            skipped_in_progress_config_ids.
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

        # Validate embedder is configured
        if not naive_rag.embedder:
            raise RagNotReadyForIndexingException(
                f"NaiveRag {naive_rag_id} has no embedder configured."
            )

        configs = IndexingService._resolve_naive_configs(
            naive_rag_id, collection, document_config_ids
        )

        DocStatus = NaiveRagDocumentConfig.NaiveRagDocumentStatus
        accepted, skipped_completed, skipped_in_progress = [], [], []
        status_changed = False

        for doc_config in configs:
            config_id = doc_config.naive_rag_document_id
            if doc_config.status in NaiveRagDocumentConfig.IN_PROGRESS_STATUSES:
                skipped_in_progress.append(config_id)
            elif doc_config.is_snapshot_current():
                if doc_config.status != DocStatus.COMPLETED:
                    IndexingService._mark_snapshot_completed(doc_config)
                    status_changed = True
                skipped_completed.append(config_id)
            else:
                accepted.append(config_id)

        if accepted:
            NaiveRagDocumentConfig.objects.filter(
                naive_rag_document_id__in=accepted
            ).update(
                status=DocStatus.INDEXING,
                error_message=None,
                error_code=NaiveRagDocumentConfig.DocumentErrorCode.NONE,
                failed_at=None,
            )
            status_changed = True

        if status_changed:
            naive_rag.update_rag_status()

        # Log preparation
        logger.info(
            f"Prepared NaiveRag {naive_rag_id}: collection={collection.collection_id}, "
            f"embedder={naive_rag.embedder.id}, accepted={accepted}, "
            f"skipped_completed={skipped_completed}, skipped_in_progress={skipped_in_progress}"
        )

        return {
            "rag_id": naive_rag_id,
            "rag_type": "naive",
            "collection_id": collection.collection_id,
            "base_rag_type_id": base_rag_type.rag_type_id,
            "accepted_config_ids": accepted,
            "skipped_completed_config_ids": skipped_completed,
            "skipped_in_progress_config_ids": skipped_in_progress,
        }

    @staticmethod
    def _resolve_naive_configs(
        naive_rag_id: int,
        collection: SourceCollection,
        document_config_ids: Optional[List[int]],
    ) -> List[NaiveRagDocumentConfig]:
        if document_config_ids:
            configs = list(
                NaiveRagDocumentConfig.objects.filter(
                    naive_rag_id=naive_rag_id,
                    naive_rag_document_id__in=document_config_ids,
                )
            )
            found = {cfg.naive_rag_document_id for cfg in configs}
            missing = [cid for cid in document_config_ids if cid not in found]
            if missing:
                raise RagException(
                    f"Document configs do not belong to NaiveRag {naive_rag_id}: {missing}"
                )
            order = {cid: i for i, cid in enumerate(document_config_ids)}
            configs.sort(key=lambda cfg: order[cfg.naive_rag_document_id])
            return configs

        # Validate collection has documents
        if not DocumentMetadata.objects.filter(source_collection=collection).exists():
            raise DocumentsNotFoundException(
                f"Collection {collection.collection_id} has no documents to index"
            )
        return list(NaiveRagDocumentConfig.objects.filter(naive_rag_id=naive_rag_id))

    @staticmethod
    def _mark_snapshot_completed(doc_config: NaiveRagDocumentConfig) -> None:
        """Flip config to COMPLETED in-place and persist. Called only when the
        live params already match the indexed snapshot (no worker dispatch needed)."""
        doc_config.mark_completed(processed_at=timezone.now())
        doc_config.save(
            update_fields=[
                "status",
                "error_message",
                "error_code",
                "failed_at",
                "processed_at",
            ]
        )

    @staticmethod
    def _prepare_graph_rag_indexing(graph_rag_id: int) -> Dict[str, Any]:
        """
        Validates and prepares GraphRag for indexing.

        Args:
            graph_rag_id: The GraphRag primary key

        Returns:
            Dict with rag_id, rag_type, collection_id, base_rag_type_id.
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
        document_count = GraphRagDocument.objects.filter(graph_rag=graph_rag).count()
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
            f"Prepared GraphRag {graph_rag_id}: collection={collection.collection_id}, "
            f"embedder={graph_rag.embedder.id}, llm={graph_rag.llm.id}"
        )
        return {
            "rag_id": graph_rag_id,
            "rag_type": "graph",
            "collection_id": collection.collection_id,
            "base_rag_type_id": base_rag_type.rag_type_id,
        }

    @staticmethod
    def mark_indexing_dispatched(rag_id: int, rag_type: str) -> None:
        """Flag the RAG PROCESSING the moment work is dispatched, so polling
        clients don't see the stale pre-dispatch status. Direct .update(), no
        status recompute. Naive is already flipped to PROCESSING atomically in
        _prepare_naive_rag_indexing (before the publish), so only graph needs it."""
        if rag_type == "graph":
            GraphRag.objects.filter(graph_rag_id=rag_id).update(
                rag_status=GraphRag.GraphRagStatus.PROCESSING
            )

    @staticmethod
    def get_rag_status(rag_id: int, rag_type: str) -> str:
        """
        Get current status of RAG implementation.

        Args:
            rag_id: The RAG primary key
            rag_type: The type of RAG ("naive" or "graph")

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
