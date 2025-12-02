import os
from loguru import logger
import cachetools

from psycopg2.errors import ForeignKeyViolation

from services.chunk_document_service import ChunkDocumentService
from models.dto.models_dto import (
    ChunkDTO,
    DocumentContentDTO,
    KnowledgeChunkDTO,
    KnowledgeQueryResultDTO,
)
from models.orm.document_models import DocumentContent
from storage.knowledge_storage import ORMKnowledgeStorage
from storage.document_chunk_storage import ORMDocumentChunkStorage
from storage.document_storage import ORMDocumentStorage

from chunkers.token_chunker import TokenChunker
from chunkers.markdown_chunker import MarkdownChunker
from chunkers.character_chunker import CharacterChunker
from chunkers.json_chunker import JSONChunker
from chunkers.html_chunker import HTMLChunker
from chunkers.csv_chunker import CSVChunker
from settings import UnitOfWork
from embedder.openai import OpenAIEmbedder
from embedder.gemini import GoogleGenAIEmbedder
from embedder.cohere import CohereEmbedder
from embedder.mistral import MistralEmbedder
from embedder.together_ai import TogetherAIEmbedder
from models.enums import *
from utils.singleton_meta import SingletonMeta

_embedder_cache = cachetools.LRUCache(maxsize=50)


class CollectionProcessorService(metaclass=SingletonMeta):

    def _get_cached_embedder(self, collection_id: int):
        """Retrieve embedder from cache or initialize it if not cached."""
        if collection_id in _embedder_cache:
            return _embedder_cache[collection_id]

        logger.info(f"Initializing embedder for collection {collection_id}")
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            embedder_config = uow_ctx.knowledge_storage.get_embedder_configuration(
                collection_id
            )
        embedder = self._set_embedder_config(embedder_config)

        _embedder_cache[collection_id] = embedder
        return embedder

    def search(self, collection_id, uuid, query, search_limit, similarity_threshold):
        embedder = self._get_cached_embedder(collection_id=collection_id)
        # Embed the query

        embedded_query = embedder.embed(query)
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            # Search in storage
            knowledge_chunk_list = uow_ctx.knowledge_storage.search(
                embedded_query=embedded_query,
                collection_id=collection_id,
                limit=search_limit,
                similarity_threshold=similarity_threshold,
            )

            # this code supports backwards capability.
            # TODO: refactor in places where this method used (human_input, realtime, crew)
            knowledge_snippets = []
            for chunk_data in knowledge_chunk_list:
                knowledge_snippets.append(chunk_data.chunk_text)

            # Logging results
            if knowledge_snippets:
                if len(knowledge_snippets) > 1:
                    logger.info(
                        f"KNOWLEDGES: {knowledge_snippets[0][:150]}\n.........\n{knowledge_snippets[-1][-150:]}"
                    )
                else:
                    logger.info(f"KNOWLEDGES: {knowledge_snippets[0][:150]}...")
            else:
                logger.warning(f"NO KNOWLEDGE CHUNKS WERE EXTRACTED!")

        knowledge_query_results = KnowledgeQueryResultDTO(
            uuid=uuid,
            collection_id=collection_id,
            retrieved_chunks=len(knowledge_chunk_list),
            results=knowledge_snippets,
            knowledge_query=query,
            search_limit=search_limit,
            similarity_threshold=similarity_threshold,
            chunks=knowledge_chunk_list,
        )

        return knowledge_query_results.model_dump()

    def process_collection(self, collection_id):
        embedder = self._get_cached_embedder(collection_id=collection_id)
        uow = UnitOfWork()

        try:
            with uow.start() as uow_ctx:
                uow_ctx.knowledge_storage.update_collection_status(
                    status=Status.PROCESSING,
                    collection_id=collection_id,
                )
                logger.info(f"Processing embeddings for collection_id: {collection_id}")

                document_list = uow_ctx.document_storage.get_documents_in_collection(
                    collection_id=collection_id,
                    status=(
                        DocumentStatus.NEW,
                        DocumentStatus.WARNING,
                        DocumentStatus.CHUNKED,
                    ),
                )

                if len(document_list) == 0:
                    logger.warning(
                        f"Collection {collection_id} must contain at least 1 new document to embed"
                    )

                for doc in document_list:
                    try:
                        logger.info(
                            f"Started processing document {doc.file_name}, ID: {doc.document_id}"
                        )
                        uow_ctx.document_storage.update_document_status(
                            status=Status.PROCESSING,
                            document_id=doc.document_id,
                        )

                        chunk_dto_list = ChunkDocumentService().proccess_chunk_document(
                            document=doc,
                        )

                        if not chunk_dto_list:
                            logger.warning(
                                f"Document: {doc.file_name} was not chunked and will not be embedded"
                            )
                            uow_ctx.document_storage.update_document_status(
                                status=Status.WARNING,
                                document_id=doc.document_id,
                            )
                            continue

                        for chunk_dto in chunk_dto_list:
                            vector = embedder.embed(chunk_dto.text)
                            uow_ctx.knowledge_storage.save_embedding(
                                chunk_id=chunk_dto.id,
                                embedding=vector,
                                document_id=doc.document_id,
                                collection_id=collection_id,
                            )

                    except ForeignKeyViolation:
                        logger.warning(
                            f"Document: {doc.file_name} was deleted and will not be embedded"
                        )
                    except Exception as e:
                        uow_ctx.document_storage.update_document_status(
                            status=Status.FAILED,
                            document_id=doc.document_id,
                        )
                        logger.error(
                            f"Error processing {doc.file_name}, ID: {doc.document_id}. Error: {e}"
                        )
                    else:
                        uow_ctx.document_storage.update_document_status(
                            status=Status.COMPLETED,
                            document_id=doc.document_id,
                        )
                        logger.success(f"Document: {doc.file_name} embedded!")

        except Exception as e:
            with uow.start() as uow_ctx:
                uow_ctx.knowledge_storage.update_collection_status(
                    status=Status.FAILED,
                    collection_id=collection_id,
                )
            logger.error(f"Error processing collection_id {collection_id}: {e}")
        else:
            self.process_collection_status(collection_id=collection_id)
            logger.info(f"Embedding finished for collection_id: {collection_id}")

    def _get_chunk_strategy(
        self, chunk_strategy, chunk_size, chunk_overlap, additional_params
    ):
        strategies = {
            "token": TokenChunker,
            "character": CharacterChunker,
            "markdown": MarkdownChunker,
            "html": HTMLChunker,
            "json": JSONChunker,
            "csv": CSVChunker,
        }
        return strategies[chunk_strategy](chunk_size, chunk_overlap, additional_params)

    def _create_default_embedding_function(self):

        return OpenAIEmbedder(
            api_key=os.getenv("OPENAI_API_KEY"), model_name="text-embedding-3-small"
        )

    # TODO: use litellm instead
    def _set_embedder_config(self, embedder_config) -> None:
        """Set the embedding configuration for the knowledge storage."""

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
                f"Failed to set custom embedder. Default embedder setted. Error: {e}"
            )
            return self._create_default_embedding_function()

    def process_collection_status(self, collection_id):
        """
        Update Collection status based on documents statuses

        FAILED: all documents Failed
        WARNING: at least 1 Warning or 1 Failed (but not all Failed),
                or mixture with CHUNKED
        PROCESSING: at least 1 Processing
        NEW: all documents are New OR no documents
        COMPLETED: all documents are Completed
        CHUNKED: all documents are Chunked
        """
        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            documents_statuses = set(
                uow.document_storage.get_documents_statuses(collection_id)
            )

        if not documents_statuses or documents_statuses == {Status.NEW}:
            current_status = Status.NEW
        elif documents_statuses == {Status.COMPLETED}:
            current_status = Status.COMPLETED
        elif documents_statuses == {Status.FAILED}:
            current_status = Status.FAILED
        elif documents_statuses == {Status.CHUNKED}:
            current_status = Status.CHUNKED
        elif Status.PROCESSING in documents_statuses:
            current_status = Status.PROCESSING
        elif (
            Status.FAILED in documents_statuses
            or Status.WARNING in documents_statuses
            or Status.CHUNKED in documents_statuses
        ):
            current_status = Status.WARNING
        else:
            # fallback
            current_status = Status.WARNING

        with uow.start() as uow_ctx:
            uow_ctx.knowledge_storage.update_collection_status(
                current_status, collection_id
            )
            logger.info(f"{current_status} was set to collection {collection_id}")
