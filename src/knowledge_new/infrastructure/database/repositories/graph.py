from domain.enums import DocumentStatusEnum, SlotEnum
from domain.models import Rag
from domain.ports.repositories import AbstractGraphRagRepository
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_input import TextDocument
from infrastructure.database.mappers.graph import (
    graph_document_orm_to_text_document,
    graph_rag_orm_to_graphrag_config,
    graph_rag_orm_to_rag,
    graph_rag_update_values,
)
from infrastructure.database.models import (
    DocumentMetadata,
    EmbeddingModel,
    GraphRag,
    GraphRagDocument,
    LLMConfig,
    LLMModel,
)
from infrastructure.database.models import EmbeddingConfig as ORMEmbeddingConfig
from infrastructure.database.repositories.base import BaseSQLAlchemyRepositoryMixin
from infrastructure.file_text_extractors import build_file_text_extractor
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import joinedload


class GraphRagSQLAlchemyRepository(BaseSQLAlchemyRepositoryMixin, AbstractGraphRagRepository):
    async def get_rag(self, rag_id: int) -> Rag | None:
        result = await self._session.execute(
            select(GraphRag).where(GraphRag.graph_rag_id == rag_id)
        )
        if (data := result.scalar_one_or_none()) is not None:
            return graph_rag_orm_to_rag(data)
        return None

    async def update_rag(self, rag: Rag):
        await self._session.execute(
            update(GraphRag)
            .where(GraphRag.graph_rag_id == rag.id)
            .values(**graph_rag_update_values(rag))
        )

    async def _get_documents(self, rag_id: int, *conditions) -> list[TextDocument]:
        result = await self._session.execute(
            select(GraphRagDocument)
            .where(GraphRagDocument.graph_rag_id == rag_id, *conditions)
            .options(
                joinedload(GraphRagDocument.document).joinedload(DocumentMetadata.document_content)
            )
        )
        rows = result.scalars().all()
        documents = []
        for row in rows:
            document = row.document
            extension = f".{document.file_type}"
            extractor = build_file_text_extractor(extension)
            text = await extractor.extract(document.document_content.content)
            documents.append(graph_document_orm_to_text_document(row, text))
        return documents

    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[TextDocument]:
        return await self._get_documents(
            rag_id,
            GraphRagDocument.graph_rag_document_id.in_(ids),
        )

    async def get_indexed_documents_excluding(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        return await self._get_documents(
            rag_id,
            GraphRagDocument.graph_rag_document_id.not_in(ids),
            GraphRagDocument.status == DocumentStatusEnum.COMPLETED,
        )

    async def update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: DocumentStatusEnum,
    ):
        await self._session.execute(
            update(GraphRagDocument)
            .where(
                GraphRagDocument.graph_rag_id == rag_id,
                GraphRagDocument.graph_rag_document_id.in_(ids),
            )
            .values(status=status)
        )

    async def has_completed_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    GraphRagDocument.graph_rag_id == rag_id,
                    GraphRagDocument.status == DocumentStatusEnum.COMPLETED,
                )
            )
        )
        return result.scalar_one()

    async def has_failed_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    GraphRagDocument.graph_rag_id == rag_id,
                    GraphRagDocument.status == DocumentStatusEnum.FAILED,
                )
            )
        )
        return result.scalar_one()

    async def has_outdated_document(self, rag_id: int) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    GraphRagDocument.graph_rag_id == rag_id,
                    GraphRagDocument.status == DocumentStatusEnum.OUTDATED,
                )
            )
        )
        return result.scalar_one()

    async def get_config(self, rag_id: int, slot: SlotEnum | None = None) -> GraphRagConfig | None:
        result = await self._session.execute(
            select(GraphRag)
            .where(GraphRag.graph_rag_id == rag_id)
            .options(
                joinedload(GraphRag.index_config),
                joinedload(GraphRag.llm)
                .joinedload(LLMConfig.model)
                .joinedload(LLMModel.llm_provider),
                joinedload(GraphRag.embedder)
                .joinedload(ORMEmbeddingConfig.model)
                .joinedload(EmbeddingModel.embedding_provider),
            )
        )
        if (rag := result.scalar_one_or_none()) is not None:
            resolved_slot = slot if slot is not None else rag.slot
            return graph_rag_orm_to_graphrag_config(rag, slot=resolved_slot)
        return None

    async def remove_rag(self, rag_id: int):
        await self._session.execute(
            delete(GraphRagDocument).where(GraphRagDocument.graph_rag_id == rag_id)
        )
        await self._session.execute(delete(GraphRag).where(GraphRag.graph_rag_id == rag_id))
