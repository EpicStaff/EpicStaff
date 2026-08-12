from pathlib import Path

from domain.enums import DocumentStatusEnum, FileExtensionEnum
from domain.errors import DocumentNotFoundError
from domain.models import (
    ChunkingConfig,
    Document,
    EmbeddingConfig,
    FoundChunk,
    IndexedChunk,
    PreviewChunk,
    Rag,
)
from domain.ports.repositories import AbstractNaiveRagRepository
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
            return Rag(
                id=orm_rag.naive_rag_id,
                status=orm_rag.rag_status,
                indexing_document_ids=set(orm_rag.indexing_document_config_ids),
                error_message=orm_rag.error_message,
                outdated_reasons=orm_rag.outdated_reasons or {},
            )
        return None

    async def update_rag(self, rag: Rag):
        await self._session.execute(
            update(NaiveRag)
            .where(NaiveRag.naive_rag_id == rag.id)
            .values(
                rag_status=rag.status,
                indexing_document_config_ids=list(rag.indexing_document_ids),
                error_message=rag.error_message,
                outdated_reasons=rag.outdated_reasons or {},
            )
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
            return EmbeddingConfig(provider=row[0].lower(), api_key=row[1], model=row[2], extra={})
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
            return self._to_document(config)
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
        return [self._to_document(c) for c in configs]

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
            [
                NaiveRagPreviewChunk(
                    naive_rag_document_config_id=document_id,
                    text=c.text,
                    chunk_index=index,
                    token_count=c.token_count,
                    overlap_start_index=c.overlap_start,
                    overlap_end_index=c.overlap_end,
                )
                for index, c in enumerate(chunks, start=1)
            ]
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
            orm_chunk = NaiveRagChunk(
                naive_rag_document_config_id=document_id,
                text=chunk.text,
                chunk_index=index,
                token_count=chunk.token_count,
                overlap_start_index=chunk.overlap_start,
                overlap_end_index=chunk.overlap_end,
            )
            orm_chunk.embedding = NaiveRagEmbedding(
                naive_rag_document_config_id=document_id, vector=chunk.vector
            )
            self._session.add(orm_chunk)
        await self._session.flush()

    async def update_document(self, rag_id: int, document: Document):
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
                error_message=document.error_message,
            )
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
                DocumentMetadata, NaiveRagDocumentConfig.document_id == DocumentMetadata.document_id
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

    @staticmethod
    def _to_document(config: NaiveRagDocumentConfig) -> Document:
        metadata = config.document
        document = Document(
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
            error_message=config.error_message,
        )

        if config.indexed_chunk_size is not None:
            document.last_indexing_config = ChunkingConfig(
                chunk_strategy=config.indexed_chunk_strategy,
                chunk_size=config.indexed_chunk_size,
                chunk_overlap=config.indexed_chunk_overlap,
                extra=config.indexed_additional_params or {},
            )

        return document
