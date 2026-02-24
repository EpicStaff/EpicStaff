from typing import List, Optional, Union
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import delete, select
from loguru import logger

from .base_storage import BaseORMStorage
from models.orm import (
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagChunk,
    NaiveRagPreviewChunk,
    NaiveRagEmbedding,
    DocumentMetadata,
)
from models.redis_models import KnowledgeChunkResponse
from chunkers.base_chunker import BaseChunkData


class ORMNaiveRagStorage(BaseORMStorage):
    """
    Storage implementation for NaiveRag operations.

    All methods work with naive_rag_id.
    Inherits shared functionality from BaseORMStorage.
    """

    # ==================== NaiveRag Operations ====================

    def get_naive_rag_by_id(self, naive_rag_id: int) -> Optional[NaiveRag]:
        """
        Get NaiveRag instance by ID with eager-loaded relationships.

        Args:
            naive_rag_id: ID of the NaiveRag

        Returns:
            NaiveRag instance or None if not found
        """
        try:
            return (
                self.session.query(NaiveRag)
                .options(
                    joinedload(NaiveRag.embedder),
                    joinedload(NaiveRag.base_rag_type),
                )
                .filter(NaiveRag.naive_rag_id == naive_rag_id)
                .one_or_none()
            )
        except Exception as e:
            logger.error(f"Failed to get NaiveRag {naive_rag_id}: {e}")
            return None

    def update_rag_status(self, naive_rag_id: int, status: str) -> bool:
        """
        Update the status of a NaiveRag.

        Args:
            naive_rag_id: ID of the NaiveRag
            status: New status (new, processing, completed, warning, failed)

        Returns:
            True if successful, False otherwise
        """
        try:
            naive_rag = self.session.get(NaiveRag, naive_rag_id)
            if not naive_rag:
                logger.warning(f"NaiveRag {naive_rag_id} not found")
                return False

            naive_rag.rag_status = status
            return True

        except Exception as e:
            logger.error(f"Failed to update NaiveRag {naive_rag_id} status: {e}")
            return False

    # ==================== Document Config Operations ====================

    def get_naive_rag_document_configs(
        self, naive_rag_id: int, status: Optional[str | tuple[str]] = None
    ) -> List[NaiveRagDocumentConfig]:
        """
        Get all document configs for a NaiveRag, optionally filtered by status.

        Args:
            naive_rag_id: ID of the NaiveRag
            status: Optional status or tuple of statuses to filter by

        Returns:
            List of NaiveRagDocumentConfig instances
        """
        try:
            query = (
                self.session.query(NaiveRagDocumentConfig)
                .options(
                    selectinload(NaiveRagDocumentConfig.document).selectinload(
                        DocumentMetadata.document_content
                    )
                )
                .filter(NaiveRagDocumentConfig.naive_rag_id == naive_rag_id)
            )

            if status:
                if isinstance(status, str):
                    query = query.filter(NaiveRagDocumentConfig.status == status)
                else:
                    query = query.filter(NaiveRagDocumentConfig.status.in_(status))

            return query.all()

        except Exception as e:
            logger.error(
                f"Failed to get document configs for NaiveRag {naive_rag_id}: {e}"
            )
            return []

    def get_naive_rag_document_config_by_id(
        self, naive_rag_document_config_id: int
    ) -> Optional[NaiveRagDocumentConfig]:
        """
        Get a specific document config by ID.

        Args:
            naive_rag_document_config_id: ID of the document config

        Returns:
            NaiveRagDocumentConfig instance or None
        """
        try:
            return (
                self.session.query(NaiveRagDocumentConfig)
                .options(
                    joinedload(NaiveRagDocumentConfig.document).joinedload(
                        DocumentMetadata.document_content
                    ),
                    joinedload(NaiveRagDocumentConfig.naive_rag),
                )
                .filter(
                    NaiveRagDocumentConfig.naive_rag_document_id
                    == naive_rag_document_config_id
                )
                .one_or_none()
            )
        except Exception as e:
            logger.error(
                f"Failed to get NaiveRagDocumentConfig {naive_rag_document_config_id}: {e}"
            )
            return None

    def update_document_config_status(
        self, naive_rag_document_config_id: int, status: str
    ) -> bool:
        """
        Update document config status.

        Args:
            naive_rag_document_config_id: ID of the document config
            status: New status

        Returns:
            True if successful, False otherwise
        """
        try:
            doc_config = self.session.get(
                NaiveRagDocumentConfig, naive_rag_document_config_id
            )
            if not doc_config:
                logger.warning(
                    f"NaiveRagDocumentConfig {naive_rag_document_config_id} not found"
                )
                return False

            doc_config.status = status
            return True

        except Exception as e:
            logger.error(
                f"Failed to update document config {naive_rag_document_config_id} status: {e}"
            )
            return False

    # ==================== Chunk Operations ====================

    def save_document_chunks(
        self, naive_rag_document_config_id: int, chunk_list: List[BaseChunkData]
    ) -> List[NaiveRagChunk]:
        """
        Save multiple chunks for a document config.

        Args:
            naive_rag_document_config_id: ID of the document config
            chunk_list: List of BaseChunkData instances

        Returns:
            List of created NaiveRagChunk instances
        """
        try:
            chunks = [
                NaiveRagChunk(
                    naive_rag_document_config_id=naive_rag_document_config_id,
                    text=chunk_data.text,
                    chunk_index=idx,
                    token_count=chunk_data.token_count,
                    overlap_start_index=chunk_data.overlap_start_index,
                    overlap_end_index=chunk_data.overlap_end_index,
                )
                for idx, chunk_data in enumerate(chunk_list, start=1)
            ]
            self.session.add_all(chunks)
            self.session.flush()
            return chunks

        except Exception as e:
            logger.error(
                f"Failed to save chunks for document config {naive_rag_document_config_id}: {e}"
            )
            raise

    def delete_chunks(self, naive_rag_document_config_id: int) -> bool:
        """
        Delete all chunks for a document config.

        Args:
            naive_rag_document_config_id: ID of the document config

        Returns:
            True if successful, False otherwise
        """
        try:
            deleted = (
                self.session.query(NaiveRagChunk)
                .filter(
                    NaiveRagChunk.naive_rag_document_config_id
                    == naive_rag_document_config_id
                )
                .delete()
            )
            return deleted > 0

        except Exception as e:
            logger.error(
                f"Failed to delete chunks for document config {naive_rag_document_config_id}: {e}"
            )
            return False

    def get_chunks_by_config_id(
        self, naive_rag_document_config_id: int
    ) -> List[NaiveRagChunk]:
        """
        Get all chunks for a document config, attached to the current session.

        Args:
            naive_rag_document_config_id: ID of the document config

        Returns:
            List of NaiveRagChunk instances (attached to current session)
        """
        try:
            chunks = (
                self.session.query(NaiveRagChunk)
                .filter(
                    NaiveRagChunk.naive_rag_document_config_id
                    == naive_rag_document_config_id
                )
                .order_by(NaiveRagChunk.chunk_index)
                .all()
            )
            return chunks

        except Exception as e:
            logger.error(
                f"Failed to get chunks for document config {naive_rag_document_config_id}: {e}"
            )
            return []

    # ==================== Preview Chunk Operations ====================

    def delete_preview_chunks(self, naive_rag_document_config_id: int) -> int:
        """
        Delete all preview chunks for a document config.

        Args:
            naive_rag_document_config_id: ID of the document config

        Returns:
            Number of deleted preview chunks
        """
        try:
            deleted = (
                self.session.query(NaiveRagPreviewChunk)
                .filter(
                    NaiveRagPreviewChunk.naive_rag_document_config_id
                    == naive_rag_document_config_id
                )
                .delete()
            )
            logger.debug(
                f"Deleted {deleted} preview chunks for config {naive_rag_document_config_id}"
            )
            return deleted

        except Exception as e:
            logger.error(
                f"Failed to delete preview chunks for config {naive_rag_document_config_id}: {e}"
            )
            raise

    def save_preview_chunks(
        self, naive_rag_document_config_id: int, chunk_list: List[BaseChunkData]
    ) -> List[NaiveRagPreviewChunk]:
        """
        Bulk save preview chunks for a document config.

        Args:
            naive_rag_document_config_id: ID of the document config
            chunk_list: List of BaseChunkData instances

        Returns:
            List of created NaiveRagPreviewChunk instances
        """
        try:
            chunks = [
                NaiveRagPreviewChunk(
                    naive_rag_document_config_id=naive_rag_document_config_id,
                    text=chunk_data.text,
                    chunk_index=idx,
                    token_count=chunk_data.token_count,
                    overlap_start_index=chunk_data.overlap_start_index,
                    overlap_end_index=chunk_data.overlap_end_index,
                )
                for idx, chunk_data in enumerate(chunk_list, start=1)
            ]
            self.session.add_all(chunks)
            self.session.flush()

            logger.debug(
                f"Saved {len(chunks)} preview chunks for config {naive_rag_document_config_id}"
            )
            return chunks

        except Exception as e:
            logger.error(
                f"Failed to save preview chunks for config {naive_rag_document_config_id}: {e}"
            )
            raise

    # ==================== Embedding Operations ====================

    def save_embedding(
        self,
        chunk_id: int,
        embedding: List[float],
        naive_rag_document_config_id: int,
    ) -> None:
        """
        Save an embedding for a chunk.

        Args:
            chunk_id: ID of the chunk
            embedding: Vector embedding
            naive_rag_document_config_id: ID of the document config

        Raises:
            Exception if save fails
        """
        try:
            embedding_obj = NaiveRagEmbedding(
                chunk_id=chunk_id,
                vector=embedding,
                naive_rag_document_config_id=naive_rag_document_config_id,
            )
            self.session.add(embedding_obj)

        except Exception as e:
            logger.error(f"Failed to save embedding for chunk {chunk_id}: {e}")
            raise

    def delete_embeddings(self, naive_rag_document_config_id: int) -> None:
        """
        Delete all embeddings for a document config.

        Args:
            naive_rag_document_config_id: ID of the document config
        """
        try:
            stmt = delete(NaiveRagEmbedding).where(
                NaiveRagEmbedding.naive_rag_document_config_id
                == naive_rag_document_config_id
            )
            self.session.execute(stmt)

        except Exception as e:
            logger.error(
                f"Failed to delete embeddings for document config {naive_rag_document_config_id}: {e}"
            )
            raise

    # ==================== Search Operations ====================

    def search(
        self,
        naive_rag_id: int,
        embedded_query: List[float],
        limit: int = 3,
        similarity_threshold: float = 0.2,
    ) -> List[KnowledgeChunkResponse]:
        """
        Search for similar chunks in a NaiveRag using vector similarity.

        Args:
            naive_rag_id: ID of the NaiveRag to search in
            embedded_query: Query vector
            limit: Maximum number of results
            similarity_threshold: Minimum similarity (0-1, where 1 is identical)

        Returns:
            List of chunk texts
        """
        try:
            # Compute similarity = 1 - cosine_distance
            similarity_expr = (
                1 - NaiveRagEmbedding.vector.cosine_distance(embedded_query)
            ).label("similarity")

            # Join through document configs to filter by naive_rag_id
            stmt = (
                select(NaiveRagChunk.text, similarity_expr, DocumentMetadata.file_name)
                .join(
                    NaiveRagEmbedding,
                    NaiveRagEmbedding.chunk_id == NaiveRagChunk.chunk_id,
                )
                .join(
                    NaiveRagDocumentConfig,
                    NaiveRagDocumentConfig.naive_rag_document_id
                    == NaiveRagChunk.naive_rag_document_config_id,
                )
                .join(
                    DocumentMetadata,
                    DocumentMetadata.document_id == NaiveRagDocumentConfig.document_id,
                )
                .where(NaiveRagDocumentConfig.naive_rag_id == naive_rag_id)
                .order_by(similarity_expr.desc())
                .limit(limit)
            )

            results = self.session.execute(stmt).all()

            final_results = []
            for i, r in enumerate(results, start=1):
                similarity = r.similarity
                if similarity is not None and similarity >= similarity_threshold:
                    logger.info(
                        f"Chunk #{i} (similarity: {similarity:.4f}): {r.text[:100]}..."
                    )
                    chunk_data = KnowledgeChunkResponse(
                        chunk_order=i,
                        chunk_similarity=round(similarity, 4),
                        chunk_text=r.text,
                        chunk_source=r.file_name,
                    )
                    final_results.append(chunk_data)

            logger.info(
                f"Returning {len(final_results)} chunks for NaiveRag {naive_rag_id} "
                f"(threshold={similarity_threshold})"
            )
            return final_results

        except Exception as e:
            logger.error(f"Search failed for NaiveRag {naive_rag_id}: {e}")
            return []
