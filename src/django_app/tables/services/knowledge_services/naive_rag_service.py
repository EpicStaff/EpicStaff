from typing import Any, Dict, List, Optional

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from loguru import logger

from tables.exceptions import (
    CollectionNotFoundException,
    DocumentConfigNotFoundException,
    EmbedderNotFoundException,
    InvalidChunkParametersException,
    NaiveRagNotFoundException,
)
from tables.models.embedding_models import EmbeddingConfig
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentMetadata,
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagPreviewChunk,
    SourceCollection,
)
from tables.validators.chunk_parameter_validator import NaiveRagDocumentConfigValidator


class NaiveRagService:
    """
    Service for NaiveRag operations.

    Handles:
    - Creating/updating NaiveRag configuration
    - Managing per-document configurations
    - Bulk operations

    Chunk-parameter validation lives in NaiveRagDocumentConfigValidator.
    """

    @staticmethod
    def get_collection(collection_id: int) -> SourceCollection:
        """Get collection by ID."""
        try:
            return SourceCollection.objects.get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

    @staticmethod
    def get_embedder(embedder_id: int) -> EmbeddingConfig:
        """Get embedder by ID."""
        try:
            return EmbeddingConfig.objects.get(pk=embedder_id)
        except EmbeddingConfig.DoesNotExist:
            raise EmbedderNotFoundException(embedder_id)

    @staticmethod
    def get_naive_rag(naive_rag_id: int) -> NaiveRag:
        """Get NaiveRag by ID."""
        try:
            return NaiveRag.objects.select_related(
                "base_rag_type", "base_rag_type__source_collection", "embedder"
            ).get(naive_rag_id=naive_rag_id)
        except NaiveRag.DoesNotExist:
            raise NaiveRagNotFoundException(naive_rag_id)

    @staticmethod
    def get_or_none_naive_rag_by_collection(collection_id: int) -> Optional[NaiveRag]:
        """
        Get NaiveRag for a collection, or None if doesn't exist.
        """
        try:
            base_rag = BaseRagType.objects.get(
                source_collection_id=collection_id, rag_type=BaseRagType.RagType.NAIVE
            )
            return NaiveRag.objects.select_related("embedder").get(
                base_rag_type=base_rag
            )
        except (BaseRagType.DoesNotExist, NaiveRag.DoesNotExist):
            return None

    @staticmethod
    @transaction.atomic
    def create_or_update_naive_rag(collection_id: int, embedder_id: int) -> NaiveRag:
        """
        Create new NaiveRag or update existing one.
        Creates BaseRagType + NaiveRag in one transaction.

        Args:
            collection_id: ID of source collection
            embedder_id: ID of embedder to use

        Returns:
            NaiveRag instance (new or updated)
        """
        # Validate collection exists
        collection = NaiveRagService.get_collection(collection_id)

        # Validate embedder exists
        embedder = NaiveRagService.get_embedder(embedder_id)

        # Check if NaiveRag already exists for this collection
        existing_naive_rag = NaiveRagService.get_or_none_naive_rag_by_collection(
            collection_id
        )

        if existing_naive_rag:
            # Update existing NaiveRag
            existing_naive_rag.embedder = embedder
            existing_naive_rag.save(update_fields=["embedder", "updated_at"])

            logger.info(
                f"Updated NaiveRag {existing_naive_rag.naive_rag_id} "
                f"for collection {collection_id}"
            )

            return existing_naive_rag

        # Create new BaseRagType
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
        )

        # Create new NaiveRag
        naive_rag = NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedder,
            rag_status=NaiveRag.NaiveRagStatus.NEW,
        )

        logger.info(
            f"Created NaiveRag {naive_rag.naive_rag_id} "
            f"for collection {collection_id}"
        )

        return naive_rag

    @staticmethod
    @transaction.atomic
    def update_document_config(
        config_id: int,
        naive_rag_id: int,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunk_strategy: Optional[str] = None,
        additional_params: Optional[Dict[str, Any]] = None,
    ) -> NaiveRagDocumentConfig:
        """
        Update existing document config. Only updates provided fields.
        Drops stale preview chunks and realigns rag_status when params actually change.

        Args:
            config_id: ID of config to update
            naive_rag_id: ID of NaiveRag (for validation)
            chunk_size: New chunk size (optional)
            chunk_overlap: New overlap (optional)
            chunk_strategy: New strategy (optional)
            additional_params: New additional params (optional)

        Returns:
            Updated config

        Raises:
            DocumentConfigNotFoundException: If config not found or doesn't belong to naive_rag
            InvalidChunkParametersException: If any field fails validation
        """
        try:
            config = NaiveRagDocumentConfig.objects.select_related(
                "document", "naive_rag"
            ).get(naive_rag_document_id=config_id)
        except NaiveRagDocumentConfig.DoesNotExist:
            raise DocumentConfigNotFoundException(config_id)

        if config.naive_rag_id != naive_rag_id:
            raise DocumentConfigNotFoundException(
                f"Config {config_id} does not belong to NaiveRag {naive_rag_id}"
            )

        updates = NaiveRagDocumentConfigValidator.build_updates(
            chunk_size, chunk_overlap, chunk_strategy, additional_params
        )
        NaiveRagDocumentConfigValidator.validate_or_raise(config, updates)

        if config.apply_param_updates(updates):
            NaiveRagService._persist_param_updates(config)
            config.naive_rag.update_rag_status()

        logger.info(f"Updated document config {config_id}")
        return config

    @staticmethod
    def _persist_param_updates(config: NaiveRagDocumentConfig) -> None:
        """Persist the in-memory mutations made by
        NaiveRagDocumentConfig.apply_param_updates: drop the now-stale preview
        and save the config. Call only when apply_param_updates returned True."""
        NaiveRagPreviewChunk.objects.filter(
            naive_rag_document_config_id=config.naive_rag_document_id
        ).delete()
        config.save()

    @staticmethod
    def begin_attempt(
        config: NaiveRagDocumentConfig, new_status
    ) -> NaiveRagDocumentConfig:
        """Flip a config into a chunking/indexing attempt status and persist."""
        config.start_attempt(new_status)
        config.save(
            update_fields=["status", "error_message", "error_code", "failed_at"]
        )
        return config

    @staticmethod
    def mark_config_failed_and_get_message(
        config: NaiveRagDocumentConfig, error_code, exc: BaseException
    ) -> str:
        """Persist FAILED state on a config and return the formatted error
        message (for surfacing to the API caller)."""
        message = config.mark_failed(error_code, exc)
        config.save(
            update_fields=["status", "error_code", "error_message", "failed_at"]
        )
        return message

    @staticmethod
    def get_document_configs_for_naive_rag(
        naive_rag_id: int,
        document_config_ids: Optional[List[int]] = None,
    ) -> List[NaiveRagDocumentConfig]:
        """
        Get document configs for a NaiveRag, ordered by file name.

        Args:
            naive_rag_id: ID of NaiveRag
            document_config_ids: Optional list of specific config IDs to return.
                IDs that don't belong to this NaiveRag are silently dropped.

        Returns:
            List of document configs with chunks_count and embeddings_count annotations
        """
        NaiveRagService.get_naive_rag(naive_rag_id)

        configs_qs = (
            NaiveRagDocumentConfig.objects.filter(naive_rag_id=naive_rag_id)
            .select_related("document")
            .annotate(
                chunks_count=Count("chunks", distinct=True),
                embeddings_count=Count("embeddings", distinct=True),
            )
            .order_by("document__file_name")
        )
        if document_config_ids:
            configs_qs = configs_qs.filter(
                naive_rag_document_id__in=document_config_ids
            )
        return list(configs_qs)

    @staticmethod
    @transaction.atomic
    def delete_naive_rag(naive_rag_id: int) -> Dict[str, Any]:
        """
        Delete NaiveRag and its BaseRagType.
        Cascades to document configs.

        Args:
            naive_rag_id: ID of NaiveRag to delete

        Returns:
            dict with deletion info
        """
        naive_rag = NaiveRagService.get_naive_rag(naive_rag_id)
        base_rag_type = naive_rag.base_rag_type
        collection_id = base_rag_type.source_collection_id

        # Count configs before deletion
        config_count = NaiveRagDocumentConfig.objects.filter(
            naive_rag=naive_rag
        ).count()

        # Delete (cascades to configs)
        base_rag_type.delete()  # This will cascade to NaiveRag and configs

        logger.info(
            f"Deleted NaiveRag {naive_rag_id} for collection {collection_id} "
            f"with {config_count} document configs"
        )

        return {
            "naive_rag_id": naive_rag_id,
            "collection_id": collection_id,
            "deleted_config_count": config_count,
        }

    @staticmethod
    @transaction.atomic
    def init_document_configs(naive_rag_id: int) -> List[NaiveRagDocumentConfig]:
        """
        Initialize document configs with defaults for documents that don't have configs yet.

        Business Logic:
        - Get all documents in the collection (via NaiveRag)
        - Get document IDs that already have configs
        - Create configs with DEFAULT values only for NEW documents (without configs)
        - Existing configs remain unchanged

        Args:
            naive_rag_id: ID of NaiveRag

        Returns:
            List of newly created configs (empty list if all docs already configured)
        """
        from tables.constants.knowledge_constants import (
            DEFAULT_CHUNK_SIZE,
            DEFAULT_CHUNK_OVERLAP,
            DEFAULT_CHUNK_STRATEGY,
        )

        # Get NaiveRag and verify it exists
        naive_rag = NaiveRagService.get_naive_rag(naive_rag_id)
        collection_id = naive_rag.base_rag_type.source_collection_id

        # Get all documents in collection
        all_documents = DocumentMetadata.objects.filter(
            source_collection_id=collection_id
        )

        if not all_documents.exists():
            logger.info(
                f"No documents found in collection {collection_id} for NaiveRag {naive_rag_id}"
            )
            return []

        # Get document IDs that already have configs
        existing_config_doc_ids = set(
            NaiveRagDocumentConfig.objects.filter(naive_rag=naive_rag).values_list(
                "document_id", flat=True
            )
        )

        # Filter documents that need new configs
        documents_without_configs = all_documents.exclude(
            document_id__in=existing_config_doc_ids
        )

        if not documents_without_configs.exists():
            logger.info(f"All documents already configured for NaiveRag {naive_rag_id}")
            return []

        # Create configs with defaults for new documents
        new_configs = []
        for document in documents_without_configs:
            # Validate strategy for file type
            if not NaiveRagDocumentConfigValidator.is_strategy_allowed(
                DEFAULT_CHUNK_STRATEGY, document.file_type
            ):
                # Skip documents incompatible with default strategy
                logger.warning(
                    f"Skipping document {document.document_id} ({document.file_type}): "
                    f"incompatible with default strategy '{DEFAULT_CHUNK_STRATEGY}'"
                )
                continue

            config = NaiveRagDocumentConfig.objects.create(
                naive_rag=naive_rag,
                document=document,
                chunk_size=DEFAULT_CHUNK_SIZE,
                chunk_overlap=DEFAULT_CHUNK_OVERLAP,
                chunk_strategy=DEFAULT_CHUNK_STRATEGY,
                additional_params={},
                status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW,
            )
            new_configs.append(config)

        if new_configs:
            naive_rag.update_rag_status()

        logger.info(
            f"Initialized {len(new_configs)} new document configs for NaiveRag {naive_rag_id}. "
            f"Existing configs unchanged: {len(existing_config_doc_ids)}"
        )

        return new_configs

    @staticmethod
    def bulk_update_document_configs_with_partial_errors(
        naive_rag_id: int,
        config_ids: List[int],
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunk_strategy: Optional[str] = None,
        additional_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Bulk update multiple document configs with partial success support.
        Updates valid configs and collects errors for invalid ones.

        config_ids non-empty and ≥1 update field are guaranteed by the
        serializer (allow_empty=False); not re-checked here.

        Args:
            naive_rag_id: ID of NaiveRag (for validation)
            config_ids: List of config IDs to update
            chunk_size: New chunk size (optional)
            chunk_overlap: New overlap (optional)
            chunk_strategy: New strategy (optional)
            additional_params: New additional params (optional)

        Returns:
            Dict with:
                - updated_count: Number of successfully updated configs
                - failed_count: Number of failed configs
                - configs: List of all configs with their current DB values
                - config_errors: Dict mapping config_id to list of error dicts
        """
        # Verify NaiveRag exists
        NaiveRagService.get_naive_rag(naive_rag_id)

        # Get all configs that belong to this naive_rag
        configs = list(
            NaiveRagDocumentConfig.objects.filter(
                naive_rag_id=naive_rag_id, naive_rag_document_id__in=config_ids
            ).select_related("document")
        )

        missing_ids = set(config_ids) - {cfg.naive_rag_document_id for cfg in configs}
        if missing_ids:
            raise DocumentConfigNotFoundException(
                f"Configs not found or don't belong to NaiveRag {naive_rag_id}: {sorted(missing_ids)}"
            )

        # Build update dict
        updates = NaiveRagDocumentConfigValidator.build_updates(
            chunk_size, chunk_overlap, chunk_strategy, additional_params
        )

        # Process each config individually
        updated_count = 0
        failed_count = 0
        config_errors: Dict[int, List[Dict[str, Any]]] = {}
        any_actual_change = False

        for config in configs:
            errors = NaiveRagDocumentConfigValidator.collect_errors(config, updates)

            # If there are errors, skip this config
            if errors:
                config_errors[config.naive_rag_document_id] = errors
                failed_count += 1
                continue

            # Update this config
            try:
                if config.apply_param_updates(updates):
                    NaiveRagService._persist_param_updates(config)
                    any_actual_change = True
                updated_count += 1
            except (IntegrityError, ValidationError) as e:
                config_errors[config.naive_rag_document_id] = [
                    {
                        "field": "general",
                        "value": None,
                        "reason": f"Failed to save config: {str(e)}",
                    }
                ]
                failed_count += 1

        if any_actual_change:
            try:
                NaiveRag.objects.get(naive_rag_id=naive_rag_id).update_rag_status()
            except Exception as e:
                # Status recompute is best-effort: the per-doc updates already
                # succeeded, so log and continue rather than masking them.
                logger.error(
                    f"Failed to recompute rag_status for NaiveRag {naive_rag_id} "
                    f"after bulk update: {e}"
                )

        logger.info(
            f"Bulk update completed: {updated_count} successful, {failed_count} failed"
        )

        return {
            "updated_count": updated_count,
            "failed_count": failed_count,
            "configs": configs,
            "config_errors": config_errors,
        }

    @staticmethod
    @transaction.atomic
    def bulk_delete_document_configs(
        naive_rag_id: int, config_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Bulk delete multiple document configs by their config IDs.

        Args:
            naive_rag_id: ID of NaiveRag (for validation)
            config_ids: List of config IDs to delete

        Returns:
            dict with deletion info

        Note: config_ids non-empty is guaranteed by the serializer
        (allow_empty=False); not re-checked here.
        """
        # Verify NaiveRag exists
        NaiveRagService.get_naive_rag(naive_rag_id)

        # Get configs that belong to this naive_rag
        configs = NaiveRagDocumentConfig.objects.filter(
            naive_rag_id=naive_rag_id, naive_rag_document_id__in=config_ids
        )

        found_ids = list(configs.values_list("naive_rag_document_id", flat=True))
        missing_ids = set(config_ids) - set(found_ids)

        if missing_ids:
            logger.warning(
                f"Configs not found or don't belong to NaiveRag {naive_rag_id}: {sorted(missing_ids)}"
            )

        deleted_count = len(found_ids)

        # Delete configs
        configs.delete()

        if deleted_count:
            NaiveRag.objects.get(naive_rag_id=naive_rag_id).update_rag_status()

        logger.info(f"Bulk deleted {deleted_count} document configs: {found_ids}")

        return {
            "deleted_count": deleted_count,
            "deleted_config_ids": found_ids,
        }

    @staticmethod
    @transaction.atomic
    def delete_document_config(config_id: int, naive_rag_id: int) -> Dict[str, Any]:
        """
        Delete a single document config.

        Args:
            config_id: ID of config to delete
            naive_rag_id: ID of NaiveRag (for validation)

        Returns:
            dict with deletion info

        Raises:
            DocumentConfigNotFoundException: If config not found or doesn't belong to naive_rag
        """
        try:
            config = NaiveRagDocumentConfig.objects.get(
                naive_rag_document_id=config_id,
            )
        except NaiveRagDocumentConfig.DoesNotExist:
            raise DocumentConfigNotFoundException(config_id)

        # Validate config belongs to the specified naive_rag
        if config.naive_rag_id != naive_rag_id:
            raise DocumentConfigNotFoundException(
                f"Config {config_id} does not belong to NaiveRag {naive_rag_id}"
            )

        document_name = config.document.file_name
        naive_rag = config.naive_rag
        config.delete()

        naive_rag.update_rag_status()

        logger.info(
            f"Deleted document config {config_id} for document '{document_name}'"
        )

        return {
            "config_id": config_id,
            "document_name": document_name,
        }

    @staticmethod
    def search_chunks(
        naive_rag_id: int,
        document_config_id: int,
        query: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search preview chunks of a document config by text query.

        Returns preview chunks whose text contains the query as a
        case-insensitive substring (internal whitespace preserved).

        Returns:
            {
                "total_matches": int,
                "preview_chunk_ids": List[int],
            }

        Raises:
            DocumentConfigNotFoundException: if config does not exist or does
                not belong to the given naive_rag.
        """

        config_exists = NaiveRagDocumentConfig.objects.filter(
            naive_rag_document_id=document_config_id,
            naive_rag_id=naive_rag_id,
        ).exists()
        if not config_exists:
            raise DocumentConfigNotFoundException(
                f"DocumentConfig {document_config_id} not found "
                f"for NaiveRag {naive_rag_id}"
            )

        if not query:
            return {
                "total_matches": 0,
                "preview_chunk_ids": [],
            }

        preview_qs = (
            NaiveRagPreviewChunk.objects.filter(
                naive_rag_document_config_id=document_config_id
            )
            .filter(text__icontains=query)
            .order_by("chunk_index")
        )

        preview_total = preview_qs.count()
        preview_chunk_ids = list(
            preview_qs.values_list("preview_chunk_id", flat=True)[
                offset : offset + limit
            ]
        )

        return {
            "total_matches": preview_total,
            "preview_chunk_ids": preview_chunk_ids,
        }

    @staticmethod
    def get_preview_chunks_by_ids(
        naive_rag_id: int,
        document_config_id: int,
        preview_chunk_ids: List[int],
    ) -> List[NaiveRagPreviewChunk]:
        """
        Return preview chunks of a document config by a list of preview_chunk_ids.

        - Validates that the config belongs to the given naive_rag.
        - Deduplicates the input ids while preserving first-occurrence order.
        - Filters chunks scoped to the config (rejects ids belonging to other
          configs / naive_rag instances).
        - Returns chunks in the same order as the deduplicated input ids.
          Missing or foreign ids are silently skipped.

        Raises:
            DocumentConfigNotFoundException: if config does not exist or does
                not belong to the given naive_rag.
        """
        config_exists = NaiveRagDocumentConfig.objects.filter(
            naive_rag_document_id=document_config_id,
            naive_rag_id=naive_rag_id,
        ).exists()
        if not config_exists:
            raise DocumentConfigNotFoundException(
                f"DocumentConfig {document_config_id} not found "
                f"for NaiveRag {naive_rag_id}"
            )

        unique_ids = list(dict.fromkeys(preview_chunk_ids))
        if not unique_ids:
            return []

        chunks = NaiveRagPreviewChunk.objects.filter(
            naive_rag_document_config_id=document_config_id,
            preview_chunk_id__in=unique_ids,
        )
        chunks_by_id = {chunk.preview_chunk_id: chunk for chunk in chunks}

        return [chunks_by_id[i] for i in unique_ids if i in chunks_by_id]
