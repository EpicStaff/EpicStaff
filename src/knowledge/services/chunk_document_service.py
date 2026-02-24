import asyncio
from collections import defaultdict
from threading import Lock
from typing import Optional

from chunkers import (
    TokenChunker,
    CharacterChunker,
    MarkdownChunker,
    HTMLChunker,
    JSONChunker,
    CSVChunker,
    BaseChunker,
    BaseChunkData,
)

from settings import UnitOfWork
from utils.singleton_meta import SingletonMeta
from utils.file_text_extractor import extract_text_from_binary
from loguru import logger
from .cancellation_token import CancellationToken


class ChunkDocumentService(metaclass=SingletonMeta):
    """
    Service for chunking documents based on RAG-specific configurations.
    Each RAG implementation can have different chunking for the same document.
    """

    def __init__(self):
        # Per-config locks to serialize delete+save operations
        # This prevents race conditions when multiple jobs target the same config
        self._config_locks: dict[int, Lock] = defaultdict(Lock)

    def _get_chunk_strategy(
        self,
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        additional_params: dict,
    ) -> BaseChunker:
        """
        Get chunker instance based on strategy.

        Args:
            chunk_strategy: Strategy name (token, character, markdown, etc.)
            chunk_size: Size of each chunk
            chunk_overlap: Overlap between chunks
            additional_params: Strategy-specific parameters

        Returns:
            BaseChunker instance
        """
        strategies = {
            "token": TokenChunker,
            "character": CharacterChunker,
            "markdown": MarkdownChunker,
            "html": HTMLChunker,
            "json": JSONChunker,
            "csv": CSVChunker,
        }
        chunker_class = strategies[chunk_strategy]
        return chunker_class(chunk_size, chunk_overlap, additional_params)

    def _get_text_content(self, binary_content: bytes, file_name: str) -> str:
        """
        Extract text from binary content based on file type.
        """
        file_type = file_name.split(".")[-1].lower() if "." in file_name else ""

        if not file_type:
            logger.warning(
                f"No file extension found in '{file_name}', assuming text file"
            )
            file_type = "txt"

        return extract_text_from_binary(binary_content, file_type)

    def process_chunk_document_in_session(
        self, uow_ctx, naive_rag_document_config_id: int
    ) -> list[dict]:
        """
        Chunk a document within an existing UnitOfWork session.
        Returns:
            List of dicts with chunk data: [{"chunk_id": int, "text": str}, ...]
        """
        # Query config
        doc_config = uow_ctx.naive_rag_storage.get_naive_rag_document_config_by_id(
            naive_rag_document_config_id=naive_rag_document_config_id
        )

        if doc_config is None:
            raise ValueError(
                f"NaiveRagDocumentConfig with id {naive_rag_document_config_id} not found"
            )

        binary_content = doc_config.document.document_content.content
        file_name = doc_config.document.file_name

        # Perform chunking (CPU-bound)
        chunk_texts = self.perform_chunking(
            binary_content=binary_content,
            file_name=file_name,
            chunk_strategy=doc_config.chunk_strategy,
            chunk_size=doc_config.chunk_size,
            chunk_overlap=doc_config.chunk_overlap,
            additional_params=doc_config.additional_params,
        )

        # Delete old chunks and embeddings
        uow_ctx.naive_rag_storage.delete_chunks(
            naive_rag_document_config_id=naive_rag_document_config_id
        )
        uow_ctx.naive_rag_storage.delete_embeddings(
            naive_rag_document_config_id=naive_rag_document_config_id
        )

        # Save new chunks
        chunks = uow_ctx.naive_rag_storage.save_document_chunks(
            naive_rag_document_config_id=naive_rag_document_config_id,
            chunk_list=chunk_texts,
        )

        # Update status
        uow_ctx.naive_rag_storage.update_document_config_status(
            naive_rag_document_config_id=naive_rag_document_config_id,
            status="chunked",
        )

        logger.success(
            f"Document {file_name} chunked into {len(chunks)} chunks "
            f"(config ID: {naive_rag_document_config_id})"
        )

        # Return as Python dicts (no ORM objects)
        chunk_data = [
            {"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in chunks
        ]

        return chunk_data

    def perform_chunking(
        self,
        binary_content: bytes,
        file_name: str,
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        additional_params: dict,
    ) -> list[BaseChunkData]:
        # include file_name to additional_params
        additional_params = {**additional_params, "file_name": file_name}

        chunker = self._get_chunk_strategy(
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            additional_params=additional_params,
        )
        text = self._get_text_content(binary_content, file_name)
        chunks = chunker.chunk(text)
        return chunks

    def process_preview_chunking(
        self,
        naive_rag_document_config_id: int,
        cancellation_token: Optional["CancellationToken"] = None,
    ) -> int:
        """
        Chunk a document and save to PREVIEW table (not final chunks).

        This method is used for the chunk preview feature, allowing users
        to test different chunking parameters before indexing.

        Args:
            naive_rag_document_config_id: ID of the document config
            cancellation_token: Optional token to check if job was cancelled.
                               Use token.is_cancelled for O(1) thread-safe check.

        Returns:
            Number of preview chunks created

        Raises:
            ValueError: If config not found
            asyncio.CancelledError: If job was cancelled
        """

        def is_cancelled() -> bool:
            return cancellation_token is not None and cancellation_token.is_cancelled

        uow = UnitOfWork()
        with uow.start() as uow_ctx:
            # Get config
            doc_config = uow_ctx.naive_rag_storage.get_naive_rag_document_config_by_id(
                naive_rag_document_config_id=naive_rag_document_config_id
            )

            if doc_config is None:
                raise ValueError(
                    f"NaiveRagDocumentConfig with id {naive_rag_document_config_id} not found"
                )

            if is_cancelled():
                logger.info(
                    f"Chunking job for config {naive_rag_document_config_id} cancelled before processing"
                )
                raise asyncio.CancelledError("Job cancelled before processing")

            binary_content = doc_config.document.document_content.content
            file_name = doc_config.document.file_name

            # Perform chunking (CPU-bound)
            logger.info(f"Starting chunking for document: {file_name}")
            chunk_texts = self.perform_chunking(
                binary_content=binary_content,
                file_name=file_name,
                chunk_strategy=doc_config.chunk_strategy,
                chunk_size=doc_config.chunk_size,
                chunk_overlap=doc_config.chunk_overlap,
                additional_params=doc_config.additional_params or {},
            )

            if is_cancelled():
                logger.info(
                    f"Chunking job for config {naive_rag_document_config_id} cancelled after chunking"
                )
                raise asyncio.CancelledError("Job cancelled after chunking")

            # Critical section: delete + save must be atomic per config
            # This lock ensures "last request wins" - if Job 1 is saving and Job 2 arrives,
            # Job 2 waits, then deletes Job 1's chunks and saves its own
            config_lock = self._config_locks[naive_rag_document_config_id]

            with config_lock:
                # Re-check cancellation after acquiring lock (might have been cancelled while waiting)
                if is_cancelled():
                    logger.info(
                        f"Chunking job for config {naive_rag_document_config_id} cancelled while waiting for lock"
                    )
                    raise asyncio.CancelledError("Job cancelled while waiting for lock")

                # Delete old preview chunks (including any from concurrent jobs)
                uow_ctx.naive_rag_storage.delete_preview_chunks(
                    naive_rag_document_config_id=naive_rag_document_config_id
                )

                # Final cancellation check before save
                if is_cancelled():
                    logger.info(
                        f"Chunking job for config {naive_rag_document_config_id} cancelled before saving"
                    )
                    raise asyncio.CancelledError("Job cancelled before saving")

                # Save new preview chunks
                chunks = uow_ctx.naive_rag_storage.save_preview_chunks(
                    naive_rag_document_config_id=naive_rag_document_config_id,
                    chunk_list=chunk_texts,
                )

                # Update status to CHUNKED
                uow_ctx.naive_rag_storage.update_document_config_status(
                    naive_rag_document_config_id=naive_rag_document_config_id,
                    status="chunked",
                )

                chunk_count = len(chunks)
                logger.success(
                    f"Preview chunking completed: {chunk_count} chunks "
                    f"for config {naive_rag_document_config_id} (document: {file_name})"
                )

                return chunk_count
