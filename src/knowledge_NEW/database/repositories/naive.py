from sqlalchemy import select, delete, update
from sqlalchemy.orm import joinedload, selectinload

from database.models import (
    NaiveRagEmbedding,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    DocumentMetadata,
    Provider,
    EmbeddingConfig as ORMEmbeddingConfig,
    EmbeddingModel,
    NaiveRag,
    NaiveRagPreviewChunk,
)
from database.repositories.base import AbstractSQLAlchemyRepository
from models import (
    EmbeddingConfig,
    Document,
    FoundChunk,
    PreviewChunk,
    IndexedChunk,
    ChunkingConfig,
)
from utils import utcnow


class NaiveRagSQLAlchemyRepository(AbstractSQLAlchemyRepository):
    """Repository for naive RAG documents, chunks, and embeddings."""

    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        """Return the embedding config for RAG `rag_id`, or `None` when it has none."""
        result = await self._session.execute(
            select(Provider.name, ORMEmbeddingConfig.api_key, EmbeddingModel.name)
            .select_from(NaiveRag)
            .join(ORMEmbeddingConfig, NaiveRag.embedder_id == ORMEmbeddingConfig.id)
            .join(EmbeddingModel, ORMEmbeddingConfig.model_id == EmbeddingModel.id)
            .join(Provider, EmbeddingModel.embedding_provider_id == Provider.id)
            .where(NaiveRag.naive_rag_id == rag_id)
        )
        if row := result.one_or_none():
            return EmbeddingConfig(
                provider=row[0].lower(), api_key=row[1], model=row[2], extra={}
            )
        return None

    async def get_document(self, rag_id: int, document_id: int) -> Document | None:
        """Return document `document_id` in RAG `rag_id`, or `None` when absent."""
        result = await self._session.execute(
            select(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
                NaiveRagDocumentConfig.document_id == document_id,
            )
            .options(
                joinedload(NaiveRagDocumentConfig.document).joinedload(
                    DocumentMetadata.document_content
                ),
                selectinload(NaiveRagDocumentConfig.preview_chunks),
            )
        )
        if config := result.scalar_one_or_none():
            return self._to_document(config)
        return None

    async def get_all_documents(self, rag_id: int) -> list[Document]:
        """Return every document in RAG `rag_id`."""
        result = await self._session.execute(
            select(NaiveRagDocumentConfig)
            .where(NaiveRagDocumentConfig.naive_rag_id == rag_id)
            .options(
                joinedload(NaiveRagDocumentConfig.document).joinedload(
                    DocumentMetadata.document_content
                ),
                selectinload(NaiveRagDocumentConfig.preview_chunks),
            )
        )
        configs = result.scalars().all()
        return [self._to_document(c) for c in configs]

    async def update_rag_status(self, rag_id: int, status: str):
        """Set the status of RAG `rag_id` to `status`."""
        await self._session.execute(
            update(NaiveRag)
            .where(NaiveRag.naive_rag_id == rag_id)
            .values(rag_status=status)
        )

    async def set_error_message(self, rag_id: int, message: str | None):
        """Set (or clear) the aggregate error message of RAG `rag_id`."""
        await self._session.execute(
            update(NaiveRag)
            .where(NaiveRag.naive_rag_id == rag_id)
            .values(error_message=message)
        )

    async def set_indexed_at(self, rag_id: int):
        """Stamp `indexed_at` on RAG `rag_id` (called on full completion)."""
        await self._session.execute(
            update(NaiveRag)
            .where(NaiveRag.naive_rag_id == rag_id)
            .values(indexed_at=utcnow())
        )

    async def save_preview_chunks(self, document_id: int, chunks: list[PreviewChunk]):
        """Replace the preview chunks of document `document_id` with `chunks`."""
        await self._session.execute(
            delete(NaiveRagPreviewChunk).where(
                NaiveRagPreviewChunk.naive_rag_document_config_id == document_id
            )
        )
        self._session.add_all(
            [
                NaiveRagPreviewChunk(
                    naive_rag_document_config_id=document_id,
                    text=c.text,
                    chunk_index=index,
                    token_count=c.token_count,
                    overlap_start_index=c.overlap_start,
                    overlap_end_index=c.overlap_end,
                )
                for index, c in enumerate(chunks)
            ]
        )
        await self._session.flush()

    async def save_indexed_chunks(self, document_id: int, chunks: list[IndexedChunk]):
        """Replace the indexed chunks and embeddings of document `document_id`.

        Note:
            Also clears the document's preview chunks.
        """
        await self._session.execute(
            delete(NaiveRagEmbedding).where(
                NaiveRagEmbedding.naive_rag_document_config_id == document_id
            )
        )
        await self._session.execute(
            delete(NaiveRagChunk).where(
                NaiveRagChunk.naive_rag_document_config_id == document_id
            )
        )
        await self._session.execute(
            delete(NaiveRagPreviewChunk).where(
                NaiveRagPreviewChunk.naive_rag_document_config_id == document_id
            )
        )
        for index, chunk in enumerate(chunks):
            orm_chunk = NaiveRagChunk(
                naive_rag_document_config_id=document_id,
                text=chunk.text,
                chunk_index=index,
                token_count=chunk.token_count,
                overlap_start_index=chunk.overlap_start,
                overlap_end_index=chunk.overlap_end,
            )
            orm_chunk.embedding = NaiveRagEmbedding(
                naive_rag_document_config_id=document_id,
                vector=chunk.vector,
            )
            self._session.add(orm_chunk)
        await self._session.flush()

    async def update_document(self, rag_id: int, document: Document):
        """Set updates of `document` in RAG `rag_id`."""
        config = document.last_indexing_config
        await self._session.execute(
            update(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_document_id == document.id,
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
            )
            .values(
                status=document.status,
                indexed_chunk_strategy=config.chunk_strategy if config else None,
                indexed_chunk_size=config.chunk_size if config else None,
                indexed_chunk_overlap=config.chunk_overlap if config else None,
                indexed_additional_params=config.extra if config else None,
                error_code=document.error_code,
                error_message=document.error_message,
                failed_at=document.failed_at,
                completed_at=document.completed_at,
            )
        )

    async def search_chunks(
        self, rag_id: int, vector: list[float], limit: int, similarity_threshold: float
    ) -> list[FoundChunk]:
        """Return the chunks in RAG `rag_id` most similar to `vector`.

        Args:
            rag_id: Identifier of the naive RAG to search.
            vector: Query embedding to compare chunks against.
            limit: Maximum number of chunks to return.
            similarity_threshold: Minimum cosine similarity a chunk must reach.

        Returns:
            Matching chunks ordered by descending similarity.
        """
        similarity = (1 - NaiveRagEmbedding.vector.cosine_distance(vector)).label(
            "similarity"
        )
        result = await self._session.execute(
            select(
                NaiveRagChunk.chunk_index,
                similarity,
                NaiveRagChunk.text,
                DocumentMetadata.file_name,
            )
            .select_from(NaiveRagEmbedding)
            .join(
                NaiveRagChunk,
                NaiveRagEmbedding.chunk_id == NaiveRagChunk.chunk_id,
            )
            .join(
                NaiveRagDocumentConfig,
                NaiveRagChunk.naive_rag_document_config_id
                == NaiveRagDocumentConfig.naive_rag_document_id,
            )
            .join(
                DocumentMetadata,
                NaiveRagDocumentConfig.document_id == DocumentMetadata.document_id,
            )
            .where(NaiveRagDocumentConfig.naive_rag_id == rag_id)
            .order_by(similarity.desc())
            .limit(limit)
        )
        rows = result.all()
        return [
            FoundChunk(
                order=r.chunk_index,
                similarity=round(r.similarity, 4),
                text=r.text,
                source=r.file_name or "",
            )
            for r in rows
            if r.similarity >= similarity_threshold
        ]

    @staticmethod
    def _to_document(config: NaiveRagDocumentConfig) -> Document:
        """Map a `NaiveRagDocumentConfig` row to a domain `Document`."""
        metadata = config.document
        return Document(
            id=config.naive_rag_document_id,
            name=metadata.file_name,
            content=metadata.document_content.content,
            config=ChunkingConfig(
                chunk_strategy=config.chunk_strategy,
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                extra=config.additional_params or {},
            ),
            status=config.status,
            last_indexing_config=(
                ChunkingConfig(
                    chunk_strategy=config.indexed_chunk_strategy,
                    chunk_size=config.indexed_chunk_size,
                    chunk_overlap=config.indexed_chunk_overlap,
                    extra=config.indexed_additional_params or {},
                )
                if config.indexed_chunk_size is not None
                else None
            ),
            preview_chunks=[
                PreviewChunk(
                    text=pc.text,
                    token_count=pc.token_count,
                    overlap_start=pc.overlap_start_index,
                    overlap_end=pc.overlap_end_index,
                )
                for pc in sorted(config.preview_chunks, key=lambda c: c.chunk_index)
            ],
            error_code=config.error_code,
            error_message=config.error_message,
            failed_at=config.failed_at,
            completed_at=config.completed_at,
        )
