from pathlib import Path

from domain.enums import DocumentStatusEnum, FileExtensionEnum
from domain.errors import DocumentNotFoundError
from domain.models import (
    Document,
    EmbeddingConfig,
    FoundChunk,
    IndexedChunk,
    PreviewChunk,
    Rag,
)
from domain.ports.repositories import AbstractNaiveRagRepository
from infrastructure.database.mappers.naive import (
    document_update_values,
    embedding_row_to_embedding_config,
    indexed_chunk_to_orm_pair,
    naive_rag_doc_config_to_document,
    naive_rag_orm_to_rag,
    naive_rag_update_values,
    preview_chunk_to_orm,
    search_rows_to_found_chunks,
)
from infrastructure.database.models import (
    DocumentMetadata,
    EmbeddingModel,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    NaiveRagEmbedding,
    NaiveRagPreviewChunk,
    Provider,
)
from infrastructure.database.models import EmbeddingConfig as ORMEmbeddingConfig
from infrastructure.database.repositories.base import BaseSQLAlchemyRepositoryMixin
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import joinedload, selectinload


class NaiveRagSQLAlchemyRepository(BaseSQLAlchemyRepositoryMixin, AbstractNaiveRagRepository):
    async def get_rag(self, rag_id: int) -> Rag | None:
        result = await self._session.execute(
            select(NaiveRag).where(NaiveRag.naive_rag_id == rag_id)
        )
        if orm_rag := result.scalar_one_or_none():
            return naive_rag_orm_to_rag(orm_rag)
        return None

    async def update_rag(self, rag: Rag):
        await self._session.execute(
            update(NaiveRag)
            .where(NaiveRag.naive_rag_id == rag.id)
            .values(**naive_rag_update_values(rag))
        )

    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        result = await self._session.execute(
            select(Provider.name, ORMEmbeddingConfig.api_key, EmbeddingModel.name)
            .select_from(NaiveRag)
            .join(ORMEmbeddingConfig, NaiveRag.embedder_id == ORMEmbeddingConfig.id)
            .join(EmbeddingModel, ORMEmbeddingConfig.model_id == EmbeddingModel.id)
            .join(Provider, EmbeddingModel.embedding_provider_id == Provider.id)
            .where(NaiveRag.naive_rag_id == rag_id)
        )
        if row := result.one_or_none():
            return embedding_row_to_embedding_config(row[0], row[1], row[2])
        return None

    async def get_document(self, rag_id: int, document_id: int) -> Document | None:
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
            return naive_rag_doc_config_to_document(config)
        return None

    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[Document]:
        result = await self._session.execute(
            select(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
                NaiveRagDocumentConfig.naive_rag_document_id.in_(ids),
            )
            .options(
                joinedload(NaiveRagDocumentConfig.document).joinedload(
                    DocumentMetadata.document_content
                ),
                selectinload(NaiveRagDocumentConfig.preview_chunks),
            )
        )
        configs = result.scalars().all()
        return [naive_rag_doc_config_to_document(c) for c in configs]

    async def has_completed_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    NaiveRagDocumentConfig.naive_rag_id == rag_id,
                    NaiveRagDocumentConfig.status == DocumentStatusEnum.COMPLETED,
                )
            )
        )
        return result.scalar_one()

    async def has_failed_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    NaiveRagDocumentConfig.naive_rag_id == rag_id,
                    NaiveRagDocumentConfig.status == DocumentStatusEnum.FAILED,
                )
            )
        )
        return result.scalar_one()

    async def has_outdated_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    NaiveRagDocumentConfig.naive_rag_id == rag_id,
                    NaiveRagDocumentConfig.status == DocumentStatusEnum.OUTDATED,
                )
            )
        )
        return result.scalar_one()

    async def save_preview_chunks(self, document_id: int, chunks: list[PreviewChunk]):
        await self._session.execute(
            delete(NaiveRagPreviewChunk).where(
                NaiveRagPreviewChunk.naive_rag_document_config_id == document_id
            )
        )
        self._session.add_all(
            [preview_chunk_to_orm(document_id, c, index) for index, c in enumerate(chunks, start=1)]
        )
        await self._session.flush()

    async def save_indexed_chunks(self, document_id: int, chunks: list[IndexedChunk]):
        await self._session.execute(
            delete(NaiveRagEmbedding).where(
                NaiveRagEmbedding.naive_rag_document_config_id == document_id
            )
        )
        await self._session.execute(
            delete(NaiveRagChunk).where(NaiveRagChunk.naive_rag_document_config_id == document_id)
        )
        await self._session.execute(
            delete(NaiveRagPreviewChunk).where(
                NaiveRagPreviewChunk.naive_rag_document_config_id == document_id
            )
        )
        for index, chunk in enumerate(chunks, start=1):
            orm_chunk, orm_embedding = indexed_chunk_to_orm_pair(document_id, chunk, index)
            orm_chunk.embedding = orm_embedding
            self._session.add(orm_chunk)
        await self._session.flush()

    async def update_document(self, rag_id: int, document: Document):
        await self._session.execute(
            update(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_document_id == document.id,
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
            )
            .values(**document_update_values(document))
        )

    async def search_chunks(
        self, rag_id: int, vector: list[float], limit: int, similarity_threshold: float
    ) -> list[FoundChunk]:
        similarity = (1 - NaiveRagEmbedding.vector.cosine_distance(vector)).label("similarity")
        result = await self._session.execute(
            select(
                NaiveRagChunk.chunk_index,
                similarity,
                NaiveRagChunk.text,
                DocumentMetadata.file_name,
            )
            .select_from(NaiveRagEmbedding)
            .join(NaiveRagChunk, NaiveRagEmbedding.chunk_id == NaiveRagChunk.chunk_id)
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
        return search_rows_to_found_chunks(result.all(), similarity_threshold)

    async def get_document_content(
        self, rag_id: int, document_id: int
    ) -> tuple[bytes, FileExtensionEnum]:
        result = await self._session.execute(
            select(NaiveRagDocumentConfig)
            .where(
                NaiveRagDocumentConfig.naive_rag_id == rag_id,
                NaiveRagDocumentConfig.naive_rag_document_id == document_id,
            )
            .options(
                joinedload(NaiveRagDocumentConfig.document).joinedload(
                    DocumentMetadata.document_content
                )
            )
        )
        config = result.scalar_one_or_none()
        if config is None:
            raise DocumentNotFoundError(rag_id=rag_id, document_id=document_id)

        metadata = config.document
        content = bytes(metadata.document_content.content)
        extension = FileExtensionEnum(Path(metadata.file_name).suffix.lower())
        return content, extension
