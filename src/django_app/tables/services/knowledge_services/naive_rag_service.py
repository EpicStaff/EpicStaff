from typing import List, Dict, Any, Optional
from django.db import transaction
from loguru import logger

from tables.models.knowledge_models import (
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
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_OVERLAP,
    MAX_CHUNK_OVERLAP,
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
        Update existing document config.
        Only updates provided fields.

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
        """
        try:
            config = NaiveRagDocumentConfig.objects.select_related(
                "document", "naive_rag"
            ).get(
                naive_rag_document_id=config_id,
            )
        except NaiveRagDocumentConfig.DoesNotExist:
            raise DocumentConfigNotFoundException(config_id)

        # Validate config belongs to the specified naive_rag
        if config.naive_rag_id != naive_rag_id:
            raise DocumentConfigNotFoundException(
                f"Config {config_id} does not belong to NaiveRag {naive_rag_id}"
            )

        # Build update dict
        updates = {}

        if chunk_size is not None:
            updates["chunk_size"] = chunk_size

        if chunk_overlap is not None:
            updates["chunk_overlap"] = chunk_overlap

        if chunk_strategy is not None:
            updates["chunk_strategy"] = chunk_strategy

        if additional_params is not None:
            updates["additional_params"] = additional_params

        # Validate each field individually (structured errors)
        final_chunk_size = updates.get("chunk_size", config.chunk_size)
        final_chunk_overlap = updates.get("chunk_overlap", config.chunk_overlap)

        errors = []

        if chunk_size is not None:
            errors.extend(
                NaiveRagService.validate_field_value("chunk_size", chunk_size)
            )

        if chunk_overlap is not None:
            errors.extend(
                NaiveRagService.validate_field_value("chunk_overlap", chunk_overlap)
            )

        if chunk_strategy is not None:
            errors.extend(
                NaiveRagService.validate_field_value(
                    "chunk_strategy", chunk_strategy, config
                )
            )

        # Cross-field validation: chunk_overlap must be less than chunk_size
        if final_chunk_overlap >= final_chunk_size:
            errors.append(
                {
                    "field": "chunk_overlap",
                    "value": final_chunk_overlap,
                    "reason": f"chunk_overlap ({final_chunk_overlap}) must be less than chunk_size ({final_chunk_size})",
                }
            )

        if errors:
            raise InvalidChunkParametersException(errors=errors)

        # Apply updates
        for field, value in updates.items():
            setattr(config, field, value)

        config.save()

        logger.info(f"Updated document config {config_id}")

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

    @staticmethod
    def validate_field_value(
        field_name: str,
        value: Any,
        current_config: Optional[NaiveRagDocumentConfig] = None,
    ) -> List[Dict[str, Any]]:
        """
        Validate a single field value and return specific error messages.

        Args:
            field_name: Name of the field ('chunk_size', 'chunk_overlap', 'chunk_strategy')
            value: Value to validate
            current_config: Current config (needed for file type validation)

        Returns:
            List of error dicts with 'field', 'value', and 'reason' keys.
            Empty list if valid.
        """
        errors = []

        if field_name == "chunk_size":
            if value < MIN_CHUNK_SIZE:
                errors.append(
                    {
                        "field": "chunk_size",
                        "value": value,
                        "reason": f"chunk_size too small (min {MIN_CHUNK_SIZE})",
                    }
                )
            elif value > MAX_CHUNK_SIZE:
                errors.append(
                    {
                        "field": "chunk_size",
                        "value": value,
                        "reason": f"chunk_size too large (max {MAX_CHUNK_SIZE})",
                    }
                )

        elif field_name == "chunk_overlap":
            if value < MIN_CHUNK_OVERLAP:
                errors.append(
                    {
                        "field": "chunk_overlap",
                        "value": value,
                        "reason": f"chunk_overlap too small (min {MIN_CHUNK_OVERLAP})",
                    }
                )
            elif value > MAX_CHUNK_OVERLAP:
                errors.append(
                    {
                        "field": "chunk_overlap",
                        "value": value,
                        "reason": f"chunk_overlap too large (max {MAX_CHUNK_OVERLAP})",
                    }
                )

        elif field_name == "chunk_strategy":
            # Validate strategy exists
            valid_strategies = [
                choice[0] for choice in NaiveRagDocumentConfig.ChunkStrategy.choices
            ]
            if value not in valid_strategies:
                errors.append(
                    {
                        "field": "chunk_strategy",
                        "value": value,
                        "reason": f"Invalid chunk_strategy. Must be one of: {', '.join(valid_strategies)}",
                    }
                )
            # Validate strategy for file type if config provided
            elif (
                current_config
                and not NaiveRagService.is_strategy_allowed_for_file_type(
                    value, current_config.document.file_type
                )
            ):
                allowed = NaiveRagService.get_allowed_strategies_for_file_type(
                    current_config.document.file_type
                )
                errors.append(
                    {
                        "field": "chunk_strategy",
                        "value": value,
                        "reason": f"chunk_strategy '{value}' is not valid for file type '{current_config.document.file_type}'. Allowed: {', '.join(sorted(allowed))}",
                    }
                )

        return errors

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
        if not config_ids:
            raise InvalidChunkParametersException("config_ids list cannot be empty")

        # Verify NaiveRag exists
        NaiveRagService.get_naive_rag(naive_rag_id)

        # Get all configs that belong to this naive_rag
        configs = list(
            NaiveRagDocumentConfig.objects.filter(
                naive_rag_id=naive_rag_id, naive_rag_document_id__in=config_ids
            ).select_related("document")
        )

        found_ids = {config.naive_rag_document_id for config in configs}
        missing_ids = set(config_ids) - found_ids

        if missing_ids:
            raise DocumentConfigNotFoundException(
                f"Configs not found or don't belong to NaiveRag {naive_rag_id}: {sorted(missing_ids)}"
            )

        # Build update dict
        updates = {}
        if chunk_size is not None:
            updates["chunk_size"] = chunk_size
        if chunk_overlap is not None:
            updates["chunk_overlap"] = chunk_overlap
        if chunk_strategy is not None:
            updates["chunk_strategy"] = chunk_strategy
        if additional_params is not None:
            updates["additional_params"] = additional_params

        if not updates:
            raise InvalidChunkParametersException(
                "At least one field must be provided for update"
            )

        # Process each config individually
        updated_count = 0
        failed_count = 0
        config_errors = {}

        for config in configs:
            errors = []

            # Determine final values for this config
            final_chunk_size = updates.get("chunk_size", config.chunk_size)
            final_chunk_overlap = updates.get("chunk_overlap", config.chunk_overlap)

            # Validate each field individually
            if chunk_size is not None:
                errors.extend(
                    NaiveRagService.validate_field_value("chunk_size", chunk_size)
                )

            if chunk_overlap is not None:
                errors.extend(
                    NaiveRagService.validate_field_value("chunk_overlap", chunk_overlap)
                )

            if chunk_strategy is not None:
                errors.extend(
                    NaiveRagService.validate_field_value(
                        "chunk_strategy", chunk_strategy, config
                    )
                )

            # Validate chunk_overlap < chunk_size with final values
            if final_chunk_overlap >= final_chunk_size:
                errors.append(
                    {
                        "field": "chunk_overlap",
                        "value": final_chunk_overlap,
                        "reason": f"chunk_overlap ({final_chunk_overlap}) must be less than chunk_size ({final_chunk_size})",
                    }
                )

            # If there are errors don't update config
            if errors:
                config_errors[config.naive_rag_document_id] = errors
                failed_count += 1
            else:
                # Update this config
                try:
                    for field, value in updates.items():
                        setattr(config, field, value)
                    config.save()
                    updated_count += 1
                except Exception as e:
                    config_errors[config.naive_rag_document_id] = [
                        {
                            "field": "general",
                            "value": None,
                            "reason": f"Failed to save config: {str(e)}",
                        }
                    ]
                    failed_count += 1

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

        Raises:
            InvalidChunkParametersException: If config_ids list is empty
            DocumentConfigNotFoundException: If any config not found or doesn't belong to naive_rag
        """
        if not config_ids:
            raise InvalidChunkParametersException("config_ids list cannot be empty")

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
        config.delete()

        logger.info(
            f"Deleted document config {config_id} for document '{document_name}'"
        )

        return {
            "config_id": config_id,
            "document_name": document_name,
        }
