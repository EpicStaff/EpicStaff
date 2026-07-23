import os
from typing import Optional
from loguru import logger
import cachetools

from services.cancellation_token import CancellationToken
from services.redis_service import RedisService

from psycopg2.errors import ForeignKeyViolation

from src.shared.models import (
    NaiveRagSearchConfig,
    BaseKnowledgeSearchMessageResponse,
    RagIndexingProgressMessage,
    derive_collection_status,
    COLLECTION_STATUS_FAILED,
    COLLECTION_STATUS_UPLOADING,
)
from rag.base_rag_strategy import BaseRAGStrategy
from services.chunk_document_service import ChunkDocumentService
from settings import UnitOfWork
from embedder.openai import OpenAIEmbedder
from embedder.gemini import GoogleGenAIEmbedder
from embedder.cohere import CohereEmbedder
from embedder.mistral import MistralEmbedder
from embedder.together_ai import TogetherAIEmbedder


_embedder_cache = cachetools.LRUCache(maxsize=50)

# Published to by NaiveRAGStrategy while indexing; read by execute_indexing
# (main.py) so the channel name is defined in exactly one place.
KNOWLEDGE_INDEXING_PROGRESS_CHANNEL = os.getenv(
    "KNOWLEDGE_INDEXING_PROGRESS_CHANNEL", "knowledge:indexing:progress"
)


class NaiveRAGStrategy(BaseRAGStrategy):
    """
    Naive RAG implementation strategy.

    All operations work with naive_rag_id (NOT collection_id).
    Uses ORMNaiveRagStorage for RAG-specific operations.
    """

    RAG_TYPE = "naive"

    def _get_cached_embedder(self, naive_rag_id: int):
        """
        Retrieve embedder from cache or initialize it if not cached.

        Args:
            naive_rag_id: ID of the NaiveRag

        Returns:
            Embedder instance
        """
        if naive_rag_id in _embedder_cache:
            return _embedder_cache[naive_rag_id]

        logger.info(f"Initializing embedder for NaiveRAG with id: {naive_rag_id}")
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            # Use base storage method with rag_type
            embedder_config = uow_ctx.naive_rag_storage.get_embedder_configuration(
                rag_id=naive_rag_id, rag_type="naive"
            )
        embedder = self._set_embedder_config(embedder_config)

        _embedder_cache[naive_rag_id] = embedder
        return embedder

    def search(
        self,
        rag_id: int,
        uuid: str,
        query: str,
        collection_id: int,
        rag_search_config: NaiveRagSearchConfig,
    ):
        """
        Search for similar chunks in a NaiveRag.

        Args:
            rag_id: ID of the NaiveRag (naive_rag_id)
            uuid: Request UUID
            query: Search query
            search_limit: Maximum number of results
            similarity_threshold: Minimum similarity threshold

        Returns:
            Dict with uuid, rag_id, and results
        """
        naive_rag_id = rag_id
        search_limit = rag_search_config.search_limit
        similarity_threshold = rag_search_config.similarity_threshold
        token_usage = {}

        embedder = self._get_cached_embedder(naive_rag_id=naive_rag_id)

        # Embed the query
        embedded_data = embedder.embed(query)

        if isinstance(embedded_data, dict):
            embedded_query = embedded_data.get("embedding", [])
            token_usage = embedded_data.get("token_usage")
        else:
            embedded_query = embedded_data

        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            # Search using naive_rag_storage

            knowledge_chunk_list = uow_ctx.naive_rag_storage.search(
                naive_rag_id=naive_rag_id,
                embedded_query=embedded_query,
                limit=search_limit,
                similarity_threshold=similarity_threshold,
            )

            knowledge_snippets = []
            for chunk_data in knowledge_chunk_list:
                knowledge_snippets.append(chunk_data.chunk_text)

            # Logging results
            if knowledge_snippets:
                logger.info(f"QUERY: [{query}]")
                if len(knowledge_snippets) > 1:
                    logger.info(
                        f"KNOWLEDGES: {knowledge_snippets[0][:150]}\n.........\n{knowledge_snippets[-1][-150:]}"
                    )
                else:
                    logger.info(f"KNOWLEDGES: {knowledge_snippets[0][:150]}...")
            else:
                logger.warning("NO KNOWLEDGE CHUNKS WERE EXTRACTED!")

        knowledge_query_results = BaseKnowledgeSearchMessageResponse(
            rag_id=naive_rag_id,
            rag_type=self.RAG_TYPE,
            collection_id=collection_id,
            uuid=uuid,
            retrieved_chunks=len(knowledge_chunk_list),
            query=query,
            chunks=knowledge_chunk_list,
            rag_search_config=rag_search_config,
            results=knowledge_snippets,
            token_usage=token_usage,
        )

        return knowledge_query_results.model_dump()

    def _publish_progress(
        self,
        *,
        collection_id: int,
        naive_rag_id: int,
        collection_status: str,
        document_config_id: Optional[int] = None,
        doc_status: Optional[str] = None,
        done: int = 0,
        total: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Publish a RagIndexingProgressMessage to KNOWLEDGE_INDEXING_PROGRESS_CHANNEL."""
        message = RagIndexingProgressMessage(
            collection_id=collection_id,
            rag_id=naive_rag_id,
            rag_type=self.RAG_TYPE,
            document_config_id=document_config_id,
            doc_status=doc_status,
            done=done,
            total=total,
            collection_status=collection_status,
            error=error,
        )
        RedisService().publish(
            KNOWLEDGE_INDEXING_PROGRESS_CHANNEL, message.model_dump()
        )

    def _derive_collection_status_for(self, naive_rag_id: int) -> str:
        """
        Best-effort lookup of the current collection_status for `naive_rag_id`,
        falling back to COLLECTION_STATUS_FAILED when the collection can't be
        resolved so a progress event never reports a false in-progress state.
        """
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            status_inputs = uow_ctx.naive_rag_storage.get_collection_status_inputs(
                naive_rag_id=naive_rag_id
            )

        if status_inputs is None:
            return COLLECTION_STATUS_FAILED

        _, has_documents, rag_statuses = status_inputs
        return derive_collection_status(rag_statuses, has_documents)

    def process_rag_indexing(self, rag_id: int):
        """
        Process RAG indexing (chunking + embedding) for a NaiveRag.

        Args:
            rag_id: ID of the NaiveRag (naive_rag_id)

        Flow:
        1. Get all document configs for this NaiveRag with status NEW/WARNING/CHUNKED
        2. For each document config:
           - Chunk the document (using ChunkDocumentService)
           - Embed all chunks
           - Update document config status
        3. Update NaiveRag status based on document config statuses

        Publishes RagIndexingProgressMessage events throughout so subscribers
        (Django's CollectionIndexingSSEView) can stream live progress. A
        terminal event is always published, even on failure paths - see
        `_derive_collection_status_for` and `update_naive_rag_status`.
        """
        naive_rag_id = rag_id

        embedder = self._get_cached_embedder(naive_rag_id=naive_rag_id)
        uow = UnitOfWork()

        with uow.start() as uow_ctx:
            status_inputs = uow_ctx.naive_rag_storage.get_collection_status_inputs(
                naive_rag_id=naive_rag_id
            )

        if status_inputs is None:
            # No collection_id to scope a progress event to - surface this as
            # an exception so the execute_indexing() safety net (main.py) logs
            # and handles it consistently with other unexpected failures.
            raise ValueError(
                f"Could not resolve source collection for naive_rag_id {naive_rag_id}"
            )

        collection_id, _, _ = status_inputs

        try:
            with uow.start() as uow_ctx:
                # Update RAG status to PROCESSING
                uow_ctx.naive_rag_storage.update_rag_status(
                    naive_rag_id=naive_rag_id,
                    status="processing",
                )
                logger.info(f"Processing embeddings for naive_rag_id: {naive_rag_id}")
                self._publish_progress(
                    collection_id=collection_id,
                    naive_rag_id=naive_rag_id,
                    collection_status=COLLECTION_STATUS_UPLOADING,
                )

                # Get all document configs for this RAG with status NEW/WARNING/CHUNKED
                document_configs = (
                    uow_ctx.naive_rag_storage.get_naive_rag_document_configs(
                        naive_rag_id=naive_rag_id,
                        status=("new", "warning", "chunked", "completed"),
                    )
                )

                if len(document_configs) == 0:
                    logger.warning(
                        f"NaiveRag {naive_rag_id} must contain at least 1 new document config to process"
                    )

                total = len(document_configs)
                for done, doc_config in enumerate(document_configs, start=1):
                    try:
                        # Extract data we need BEFORE any operations
                        config_id = doc_config.naive_rag_document_id
                        file_name = doc_config.document.file_name

                        logger.info(
                            f"Started processing document {file_name}, config ID: {config_id}"
                        )

                        # Update document config status to PROCESSING
                        uow_ctx.naive_rag_storage.update_document_config_status(
                            naive_rag_document_config_id=config_id,
                            status="processing",
                        )
                        self._publish_progress(
                            collection_id=collection_id,
                            naive_rag_id=naive_rag_id,
                            document_config_id=config_id,
                            doc_status="processing",
                            done=done - 1,
                            total=total,
                            collection_status=COLLECTION_STATUS_UPLOADING,
                        )

                        # Chunk the document in the SAME session
                        # Returns simple dicts: [{"chunk_id": int, "text": str}, ...]
                        chunk_data_list = (
                            ChunkDocumentService().process_chunk_document_in_session(
                                uow_ctx=uow_ctx,
                                naive_rag_document_config_id=config_id,
                            )
                        )

                        if not chunk_data_list:
                            logger.warning(
                                f"Document: {file_name} was not chunked and will not be embedded"
                            )
                            uow_ctx.naive_rag_storage.update_document_config_status(
                                naive_rag_document_config_id=config_id,
                                status="warning",
                            )
                            self._publish_progress(
                                collection_id=collection_id,
                                naive_rag_id=naive_rag_id,
                                document_config_id=config_id,
                                doc_status="warning",
                                done=done,
                                total=total,
                                collection_status=COLLECTION_STATUS_UPLOADING,
                            )
                            continue

                        # Embed all chunks (using simple dict data)
                        for chunk_data in chunk_data_list:
                            embedded_data = embedder.embed(chunk_data["text"])

                            if isinstance(embedded_data, dict):
                                vector = embedded_data.get("embedding", [])
                            else:
                                vector = embedded_data

                            uow_ctx.naive_rag_storage.save_embedding(
                                chunk_id=chunk_data["chunk_id"],
                                embedding=vector,
                                naive_rag_document_config_id=config_id,
                            )

                    except ForeignKeyViolation:
                        logger.warning(
                            f"Document: {file_name} was deleted and will not be embedded"
                        )
                        self._publish_progress(
                            collection_id=collection_id,
                            naive_rag_id=naive_rag_id,
                            document_config_id=config_id,
                            doc_status="warning",
                            done=done,
                            total=total,
                            collection_status=COLLECTION_STATUS_UPLOADING,
                            error="Document was deleted during indexing",
                        )
                    except Exception as e:
                        uow_ctx.naive_rag_storage.update_document_config_status(
                            naive_rag_document_config_id=config_id,
                            status="failed",
                        )
                        logger.error(
                            f"Error processing {file_name}, config ID: {config_id}. Error: {e}"
                        )
                        self._publish_progress(
                            collection_id=collection_id,
                            naive_rag_id=naive_rag_id,
                            document_config_id=config_id,
                            doc_status="failed",
                            done=done,
                            total=total,
                            collection_status=COLLECTION_STATUS_UPLOADING,
                            error=str(e),
                        )
                    else:
                        uow_ctx.naive_rag_storage.update_document_config_status(
                            naive_rag_document_config_id=config_id,
                            status="completed",
                        )
                        logger.success(f"Document: {file_name} embedded!")
                        self._publish_progress(
                            collection_id=collection_id,
                            naive_rag_id=naive_rag_id,
                            document_config_id=config_id,
                            doc_status="completed",
                            done=done,
                            total=total,
                            collection_status=COLLECTION_STATUS_UPLOADING,
                        )

        except Exception as e:
            logger.error(f"Error processing naive_rag_id {naive_rag_id}: {e}")
            with uow.start() as uow_ctx:
                status_updated = uow_ctx.naive_rag_storage.update_rag_status(
                    naive_rag_id=naive_rag_id,
                    status="failed",
                )
            if not status_updated:
                logger.error(
                    f"Failed to persist 'failed' status for NaiveRag {naive_rag_id}; "
                    "publishing terminal progress event regardless."
                )
            # ROBUSTNESS: always publish a terminal event, even if the DB
            # write above failed, so the live stream never dead-ends on
            # an in-progress status.
            self._publish_progress(
                collection_id=collection_id,
                naive_rag_id=naive_rag_id,
                collection_status=self._derive_collection_status_for(naive_rag_id),
                error=str(e),
            )
        else:
            self.update_naive_rag_status(
                naive_rag_id=naive_rag_id, collection_id=collection_id
            )
            logger.info(f"Embedding finished for naive_rag_id: {naive_rag_id}")

    def update_naive_rag_status(self, naive_rag_id: int, collection_id: int) -> None:
        """
        Update NaiveRag status based on document config statuses, then publish
        the resulting terminal RagIndexingProgressMessage.
        #TODO: refactor statuces
        Status Logic:
        - NEW: all configs are New OR no configs
        - COMPLETED: all configs are Completed
        - FAILED: all configs are Failed
        - PROCESSING: at least 1 config is Processing
        - WARNING: mixed statuses or at least 1 Warning/Failed (but not all Failed)
        - CHUNKED: all configs are Chunked

        Args:
            naive_rag_id: ID of the NaiveRag
            collection_id: ID of the owning SourceCollection (already resolved
                by the caller, avoiding a second lookup here)
        """
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            # Get all document configs for this RAG
            doc_configs = uow_ctx.naive_rag_storage.get_naive_rag_document_configs(
                naive_rag_id=naive_rag_id
            )

            # Get all statuses
            config_statuses = set(config.status for config in doc_configs)

        # Determine RAG status based on config statuses
        # TODO: refactor statuces
        if not config_statuses or config_statuses == {"new"}:
            current_status = "new"
        elif config_statuses == {"completed"}:
            current_status = "completed"
        elif config_statuses == {"failed"}:
            current_status = "failed"
        elif config_statuses == {"chunked"}:
            current_status = "chunked"
        elif "processing" in config_statuses:
            current_status = "processing"
        elif (
            "failed" in config_statuses
            or "warning" in config_statuses
            or "chunked" in config_statuses
        ):
            current_status = "warning"
        else:
            # Fallback
            current_status = "warning"

        with uow.start() as uow_ctx:
            status_updated = uow_ctx.naive_rag_storage.update_rag_status(
                naive_rag_id=naive_rag_id, status=current_status
            )
            status_inputs = uow_ctx.naive_rag_storage.get_collection_status_inputs(
                naive_rag_id=naive_rag_id
            )

        if status_updated:
            logger.info(f"Status '{current_status}' was set to NaiveRag {naive_rag_id}")
            if status_inputs is not None:
                _, has_documents, rag_statuses = status_inputs
                collection_status = derive_collection_status(
                    rag_statuses, has_documents
                )
            else:
                collection_status = COLLECTION_STATUS_FAILED
        else:
            # ROBUSTNESS: update_rag_status swallows its own DB errors and
            # returns False - the persisted rag_status is now stale (still
            # whatever it was before this call), so `status_inputs` reflects
            # that stale value too and cannot be trusted to derive
            # collection_status from (it could still resolve to an
            # in-progress value, e.g. "processing"). Hard-fallback to
            # "failed" instead of deriving from unreliable data, so the
            # stream never dead-ends on an in-progress status.
            logger.error(
                f"Failed to persist status '{current_status}' for NaiveRag {naive_rag_id}; "
                "publishing 'failed' terminal progress event as a safe fallback."
            )
            current_status = "failed"
            collection_status = COLLECTION_STATUS_FAILED

        self._publish_progress(
            collection_id=collection_id,
            naive_rag_id=naive_rag_id,
            collection_status=collection_status,
            error=(
                "NaiveRag indexing finished with 'failed' status"
                if current_status == "failed"
                else None
            ),
        )

    def _create_default_embedding_function(self):
        """Create default OpenAI embedder."""
        return OpenAIEmbedder(
            api_key=os.getenv("OPENAI_API_KEY"), model_name="text-embedding-3-small"
        )

    def _set_embedder_config(self, embedder_config):
        """
        Set the embedding configuration.

        Args:
            embedder_config: Dict with api_key, model_name, provider

        Returns:
            Embedder instance

        TODO: use litellm instead
        """
        try:
            provider = embedder_config["provider"].lower()
            provider_to_class = {
                "openai": OpenAIEmbedder,
                "gemini": GoogleGenAIEmbedder,
                "cohere": CohereEmbedder,
                "mistral": MistralEmbedder,
                "together_ai": TogetherAIEmbedder,
            }
            embedder_class = provider_to_class.get(provider)
            if embedder_class is None:
                raise ValueError(f"Embedder provider '{provider}' is not supported.")

            logger.info(f"Embedder class: {embedder_class.__name__}")

            return embedder_class(
                api_key=embedder_config["api_key"],
                model_name=embedder_config["model_name"],
            )
        except Exception as e:
            logger.info(
                f"Failed to set custom embedder. Using default embedder. Error: {e}"
            )
            return self._create_default_embedding_function()

    # ==================== Preview Chunking ====================

    def process_preview_chunking(
        self,
        document_config_id: int,
        cancellation_token: Optional["CancellationToken"] = None,
    ) -> int:
        """
        Perform preview chunking for a NaiveRag document config.

        Delegates to ChunkDocumentService for the actual chunking work.
        Cleanup of old preview chunks is handled inside ChunkDocumentService.

        Args:
            document_config_id: naive_rag_document_config_id
            cancellation_token: Optional token to check if job was cancelled

        Returns:
            Number of preview chunks created
        """
        return ChunkDocumentService().process_preview_chunking(
            naive_rag_document_config_id=document_config_id,
            cancellation_token=cancellation_token,
        )
