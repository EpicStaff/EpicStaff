from typing import List, Dict, Any, Optional

from django.db import transaction
from loguru import logger

from tables.models.knowledge_models import (
    NaiveRagPreviewChunk,
    SourceCollection,
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
    DocumentMetadata,
)
from tables.models.embedding_models import EmbeddingConfig
from tables.exceptions import (
    NaiveRagNotFoundException,
    DocumentConfigNotFoundException,
    EmbedderNotFoundException,
    InvalidChunkParametersException,
    CollectionNotFoundException,
)
from tables.constants.knowledge_constants import (
    UNIVERSAL_STRATEGIES,
    FILE_TYPE_SPECIFIC_STRATEGIES,
)


class NaiveRagService:
    """
    Service for NaiveRag operations.

    Handles:
    - Creating/updating NaiveRag configuration
    - Managing per-document configurations
    - Bulk operations
    """

    @staticmethod
    def get_allowed_strategies_for_file_type(file_type: str) -> set:
        specific = FILE_TYPE_SPECIFIC_STRATEGIES.get(file_type, set())
        return UNIVERSAL_STRATEGIES | specific

    @staticmethod
    def is_strategy_allowed_for_file_type(strategy: str, file_type: str) -> bool:
        allowed = NaiveRagService.get_allowed_strategies_for_file_type(file_type)
        return strategy in allowed

    @staticmethod
    def validate_strategy_for_file_type(
        chunk_strategy: str, file_type: str, file_name: str
    ) -> None:
        """
        Validate that chunk strategy is allowed for the file type.

        Business Rules:
        - token, character: Allowed for ALL file types
        - json: Only for JSON files
        - markdown: Only for MD files
        - html: Only for HTML files
        - csv: Only for CSV files
        """
        if not NaiveRagService.is_strategy_allowed_for_file_type(
            chunk_strategy, file_type
        ):
            allowed = NaiveRagService.get_allowed_strategies_for_file_type(file_type)
            raise InvalidChunkParametersException(
                f"Strategy '{chunk_strategy}' is not allowed for file type '{file_type}'. "
                f"File '{file_name}' can only use strategies: {', '.join(sorted(allowed))}"
            )

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

    @classmethod
    def _create_rag(
        cls, collection: SourceCollection, embedding_config: EmbeddingConfig,
    ) -> NaiveRag:
        base_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
        )

        rag = NaiveRag.objects.create(
            base_rag_type=base_rag_type,
            embedder=embedding_config,
            rag_status=NaiveRag.NaiveRagStatus.NEW,
        )

        logger.info(
            "Created NaiveRag {} for collection {}",
            rag.naive_rag_id,
            collection.collection_id,
        )

        return rag

    @classmethod
    def _update_rag(
        cls, rag: NaiveRag, collection: SourceCollection, embedding_config: EmbeddingConfig,
    ) -> NaiveRag:
        updated_fields = set()
        embedding_provider_changed = (
            rag.embedder is None
            or rag.embedder.model.embedding_provider != embedding_config.model.embedding_provider
        )

        if rag.embedder is None or rag.embedder.pk != embedding_config.pk:
            if embedding_provider_changed:
                rag.add_outdated_reason(
                    code="changed_embedding_config",
                    detail="Embedding config was changed.",
                )
                rag.rag_status = rag.NaiveRagStatus.OUTDATED
                updated_fields.update(["rag_status", "outdated_reasons"])
            rag.embedder = embedding_config
            updated_fields.add("embedder")

        if updated_fields:
            rag.save(update_fields=updated_fields)

        if embedding_provider_changed:
            rag.naive_rag_configs.filter(
                status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED
            ).update(status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.OUTDATED)

        logger.info(
            "Updated NaiveRag {} for collection {}",
            rag.naive_rag_id,
            collection.collection_id,
        )

        return rag

    @classmethod
    @transaction.atomic
    def create_or_update_naive_rag(
        cls, collection_id: int, embedder_id: int
    ) -> NaiveRag:
        """
        Create new NaiveRag or update existing one.
        Creates BaseRagType + NaiveRag in one transaction.

        Args:
            collection_id: ID of source collection
            embedder_id: ID of embedder to use

        Returns:
            NaiveRag instance (new or updated)
        """
        collection = cls.get_collection(collection_id)
        embedder = cls.get_embedder(embedder_id)
        rag = cls.get_or_none_naive_rag_by_collection(collection_id)

        if rag is not None:
            rag = cls._update_rag(rag, collection, embedder)
        else:
            rag = cls._create_rag(collection, embedder)

        return rag

    @classmethod
    def _update_document_config(
        cls,
        config: NaiveRagDocumentConfig,
        data: dict[str, Any],
        *,
        commit: bool = True,
    ) -> tuple[NaiveRagDocumentConfig, set[str]]:
        chunk_size = data.get("chunk_size", config.chunk_size)
        chunk_overlap = data.get("chunk_overlap", config.chunk_overlap)
        if chunk_overlap >= chunk_size:
            reason = "'chunk_overlap' must be less than 'chunk_size'"
            raise InvalidChunkParametersException(
                detail=reason,
                errors=[{"field": "chunk_overlap", "value": chunk_overlap, "reason": reason}],
            )

        chunk_strategy = data.get("chunk_strategy", "")
        is_allowed_strategy = cls.is_strategy_allowed_for_file_type(
            chunk_strategy, config.document.file_type
        )
        if chunk_strategy and not is_allowed_strategy:
            allowed = cls.get_allowed_strategies_for_file_type(
                config.document.file_type
            )
            reason = (
                f"chunk_strategy '{chunk_strategy}' is not valid"
                f" for file type '{config.document.file_type}."
                f" Allowed: {', '.join(sorted(allowed))}"
            )
            raise InvalidChunkParametersException(
                detail=reason,
                errors=[ {"field": "chunk_strategy", "value": chunk_strategy, "reason": reason}],
            )

        updated_fields = set()
        for field, value in data.items():
            old_value = getattr(config, field)
            if value is not None and old_value != value:
                updated_fields.add(field)
                setattr(config, field, value)

        if updated_fields:
            if config.status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED:
                config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.OUTDATED
                config.add_outdated_reason(
                    code="document_config_changed",
                    detail="Document config was changed.",
                )
                updated_fields.update(["status", "outdated_reasons"])
            if commit:
                config.save(update_fields=updated_fields)

        return config, updated_fields

    @classmethod
    @transaction.atomic
    def update_document_config(
        cls,
        config_id: int,
        naive_rag_id: int,
        data: dict[str, Any],
    ) -> NaiveRagDocumentConfig:
        """
        Update existing document config.
        Only updates provided fields.

        Args:
            config_id: ID of config to update
            naive_rag_id: ID of NaiveRag (for validation)
            data: Data to update document config.

        Returns:
            Updated config

        Raises:
            DocumentConfigNotFoundException: If config not found or doesn't belong to naive_rag
        """
        try:
            rag = cls.get_naive_rag(naive_rag_id)
            config = (
                NaiveRagDocumentConfig.objects
                .select_related("document", "naive_rag")
                .get(naive_rag_document_id=config_id, naive_rag_id=naive_rag_id)
            )  # fmt: off

        except NaiveRagDocumentConfig.DoesNotExist:
            raise DocumentConfigNotFoundException(config_id)

        config, updated_fields = cls._update_document_config(config, data)
        rag_updated_fields = set()
        if "status" in updated_fields:
            rag.add_outdated_reason(
                "document_config_changed", "Document config was changed."
            )
            rag_updated_fields.add("outdated_reasons")
        if rag.update_rag_status():
            rag_updated_fields.add("rag_status")
        if rag_updated_fields:
            rag.save(update_fields=rag_updated_fields)
        return config

    @staticmethod
    def get_document_configs_for_naive_rag(
        naive_rag_id: int,
    ) -> List[NaiveRagDocumentConfig]:
        """
        Get all document configs for a NaiveRag.

        Args:
            naive_rag_id: ID of NaiveRag

        Returns:
            List of document configs
        """
        # Verify NaiveRag exists
        NaiveRagService.get_naive_rag(naive_rag_id)

        return list(
            NaiveRagDocumentConfig.objects.filter(naive_rag_id=naive_rag_id)
            .select_related("document")
            .order_by("document__file_name")
        )

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
            if not NaiveRagService.is_strategy_allowed_for_file_type(
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

        logger.info(
            f"Initialized {len(new_configs)} new document configs for NaiveRag {naive_rag_id}. "
            f"Existing configs unchanged: {len(existing_config_doc_ids)}"
        )

        return new_configs

    @classmethod
    @transaction.atomic
    def bulk_update_document_configs_with_partial_errors(
        cls,
        naive_rag_id: int,
        data: list[dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Bulk update multiple document configs with partial success support.
        Updates valid configs and collects errors for invalid ones.

        Args:
            naive_rag_id: ID of NaiveRag (for validation)
            data: Data to update document config.

        Returns:
            Dict with:
                - updated_count: Number of successfully updated configs
                - failed_count: Number of failed configs
                - configs: List of all configs with their current DB values
                - config_errors: Dict mapping config_id to list of error dicts
        """
        rag = cls.get_naive_rag(naive_rag_id)

        config_ids = {i["id"] for i in data}
        config_query = (
            NaiveRagDocumentConfig.objects
            .filter(naive_rag_id=naive_rag_id, naive_rag_document_id__in=config_ids)
            .select_related("document")
        )  # fmt: off
        config_map = {c.naive_rag_document_id: c for c in config_query}
        missing_ids = config_ids - set(config_map.keys())
        if missing_ids:
            raise DocumentConfigNotFoundException(
                f"Configs not found or don't belong to"
                f" NaiveRag {naive_rag_id}: {sorted(missing_ids)}"
            )

        errors = {}
        total_updated_fields = set()
        total_updated_configs = []
        total_unupdated_configs = []
        total_failed_configs = []
        for updated_data in data:
            config = config_map[updated_data.pop("id")]
            try:
                config, updated_fields = cls._update_document_config(
                    config, updated_data, commit=False
                )
                if updated_fields:
                    total_updated_fields.update(updated_fields)
                    total_updated_configs.append(config)
                else:
                    total_unupdated_configs.append(config)

            except InvalidChunkParametersException as e:
                errors[config.naive_rag_document_id] = e.errors
                total_failed_configs.append(config)

        if total_updated_configs:
            NaiveRagDocumentConfig.objects.bulk_update(
                total_updated_configs,
                fields=total_updated_fields,
                batch_size=100,
            )
            rag_updated_fields = set()
            if "status" in total_updated_fields:
                rag.add_outdated_reason(
                    "document_config_changed", "Document config was changed."
                )
                rag_updated_fields.add("outdated_reasons")
            if rag.update_rag_status():
                rag_updated_fields.add("rag_status")
            if rag_updated_fields:
                rag.save(update_fields=rag_updated_fields)

        updated = len(total_updated_configs)
        unupdated = len(total_unupdated_configs)
        failed = len(total_failed_configs)

        logger.info(
            "Bulk update completed: Updated={}, Unupdated={}, Failed={}",
            updated,
            unupdated,
            failed,
        )

        return {
            "updated": updated,
            "unupdated": unupdated,
            "failed": failed,
            "configs": total_updated_configs + total_unupdated_configs + total_failed_configs,
            "errors": errors,
        }

    @staticmethod
    def sync_rag_status_after_config_removal(rag: NaiveRag) -> None:
        updated_fields = set()
        has_outdated = (
            rag.naive_rag_configs
            .filter(status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.OUTDATED)
            .exists()
        )  # fmt: off
        if not has_outdated and rag.outdated_reasons:
            rag.clear_outdated_reason()
            updated_fields.add("outdated_reasons")
        if rag.update_rag_status():
            updated_fields.add("rag_status")
        if updated_fields:
            rag.save(update_fields=updated_fields)

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

        Raises:
            InvalidChunkParametersException: If config_ids list is empty
            DocumentConfigNotFoundException: If any config not found or doesn't belong to naive_rag
        """
        if not config_ids:
            raise InvalidChunkParametersException("config_ids list cannot be empty")

        rag = NaiveRagService.get_naive_rag(naive_rag_id)

        configs = NaiveRagDocumentConfig.objects.filter(
            naive_rag_id=naive_rag_id,
            naive_rag_document_id__in=config_ids,
        )
        found_ids = list(configs.values_list("naive_rag_document_id", flat=True))
        missing_ids = set(config_ids) - set(found_ids)
        if missing_ids:
            logger.warning(
                f"Configs not found or don't belong to NaiveRag {naive_rag_id}: {sorted(missing_ids)}"
            )

        configs.delete()
        NaiveRagService.sync_rag_status_after_config_removal(rag)
        deleted = len(found_ids)
        logger.info(f"Bulk deleted {deleted} document configs: {found_ids}")

        return {
            "deleted_count": deleted,
            "deleted_config_ids": sorted(found_ids),
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

        rag = config.naive_rag
        document_name = config.document.file_name
        config.delete()
        NaiveRagService.sync_rag_status_after_config_removal(rag)

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
        chunks_by_id = {c.preview_chunk_id: c for c in chunks}

        return [chunks_by_id[i] for i in unique_ids if i in chunks_by_id]
