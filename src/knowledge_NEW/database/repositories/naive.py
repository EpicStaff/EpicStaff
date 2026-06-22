from sqlalchemy import select, delete, update
from sqlalchemy.orm import joinedload, selectinload

from database.models import (
    NaiveRagDocumentConfig,
    DocumentMetadata,
    NaiveRagPreviewChunk,
)
from database.repositories.base import AbstractSQLAlchemyRepository
from models import (
    Document,
    PreviewChunk,
    ChunkingConfig,
)


class NaiveRagSQLAlchemyRepository(AbstractSQLAlchemyRepository):
    """Repository for naive RAG documents, chunks, and embeddings."""

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

    async def update_document(self, rag_id: int, document: Document):
        """Set the status of `document` in RAG `rag_id`."""
        await self._session.execute(
            update(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_document_id == document.id,
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
            )
            .values(status=document.status)
        )

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
            preview_chunks=[
                PreviewChunk(
                    text=pc.text,
                    token_count=pc.token_count,
                    overlap_start=pc.overlap_start_index,
                    overlap_end=pc.overlap_end_index,
                )
                for pc in sorted(config.preview_chunks, key=lambda c: c.chunk_index)
            ],
        )
