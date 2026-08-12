from domain.enums import DocumentStatusEnum
from domain.models import Rag
from domain.ports.repositories import AbstractGraphRagRepository
from graphrag.config.models.cluster_graph_config import ClusterGraphConfig
from graphrag.config.models.extract_graph_config import ExtractGraphConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_chunking.chunking_config import ChunkingConfig
from graphrag_input import TextDocument
from graphrag_llm.config import ModelConfig
from infrastructure.database.models import (
    DocumentMetadata,
    EmbeddingConfig as ORMEmbeddingConfig,
    EmbeddingModel,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    LLMConfig,
    LLMModel,
)
from infrastructure.database.repositories.base import BaseSQLAlchemyRepositoryMixin
from infrastructure.file_text_extractors import build_file_text_extractor
from infrastructure.graphrag.storages import create_storage_config
from infrastructure.graphrag.vector_stores import create_vector_store_config
from sqlalchemy import exists, select, update
from sqlalchemy.orm import joinedload


class GraphRagSQLAlchemyRepository(BaseSQLAlchemyRepositoryMixin, AbstractGraphRagRepository):
    async def get_rag(self, rag_id: int) -> Rag | None:
        result = await self._session.execute(
            select(GraphRag).where(GraphRag.graph_rag_id == rag_id)
        )
        if (data := result.scalar_one_or_none()) is not None:
            return Rag(
                id=data.graph_rag_id,
                status=data.rag_status,
                indexing_document_ids=set(data.indexing_document_config_ids),
                error_message=data.error_message,
                outdated_reasons=data.outdated_reasons or {},
            )
        return None

    async def update_rag(self, rag: Rag):
        await self._session.execute(
            update(GraphRag)
            .where(GraphRag.graph_rag_id == rag.id)
            .values(
                rag_status=rag.status,
                indexing_document_config_ids=list(rag.indexing_document_ids),
                error_message=rag.error_message,
                outdated_reasons=rag.outdated_reasons or {},
            )
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
            documents.append(
                TextDocument(
                    id=str(row.graph_rag_document_id),
                    text=text,
                    title=document.file_name,
                    creation_date=row.created_at.isoformat(),
                    raw_data={"status": row.status},
                )
            )
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

    async def get_config(self, rag_id: int) -> GraphRagConfig | None:
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
            return self._to_graph_rag_config(rag)
        return None

    def _to_graph_rag_config(self, rag: GraphRag) -> GraphRagConfig:
        llm_config: LLMConfig = rag.llm
        embedding_config: ORMEmbeddingConfig = rag.embedder
        index_config: GraphRagIndexConfig = rag.index_config
        return GraphRagConfig(
            completion_models={
                "default_completion_model": self._build_completion_model(llm_config)
            },
            embedding_models={
                "default_embedding_model": self._build_embedding_model(embedding_config)
            },
            chunking=self._build_chunking_config(index_config),
            extract_graph=self._build_extract_graph_config(index_config),
            cluster_graph=self._build_cluster_graph_config(index_config),
            input_storage=create_storage_config(rag_id=rag.graph_rag_id, subdir="input"),
            output_storage=create_storage_config(rag_id=rag.graph_rag_id, subdir="output"),
            update_output_storage=create_storage_config(
                rag_id=rag.graph_rag_id,
                subdir="update_output",
            ),
            vector_store=create_vector_store_config(rag_id=rag.graph_rag_id),
        )

    @staticmethod
    def _build_completion_model(llm_config: LLMConfig) -> ModelConfig:
        llm_model: LLMModel = llm_config.model

        call_args = {}
        if llm_config.temperature is not None:
            call_args["temperature"] = llm_config.temperature
        if llm_config.max_tokens is not None:
            call_args["max_tokens"] = llm_config.max_tokens
        if llm_config.top_p is not None:
            call_args["top_p"] = llm_config.top_p

        return ModelConfig(
            model_provider=llm_model.llm_provider.name,
            model=llm_model.name,
            api_key=llm_config.api_key,
            api_base=llm_model.base_url,
            api_version=llm_model.api_version,
            call_args=call_args,
        )

    @staticmethod
    def _build_embedding_model(embedder_config: ORMEmbeddingConfig) -> ModelConfig:
        embedding_model: EmbeddingModel = embedder_config.model
        return ModelConfig(
            model_provider=embedding_model.embedding_provider.name,
            model=embedding_model.name,
            api_key=embedder_config.api_key,
            api_base=embedding_model.base_url,
        )

    @staticmethod
    def _build_chunking_config(index_config: GraphRagIndexConfig) -> ChunkingConfig:
        return ChunkingConfig(
            type=index_config.chunk_strategy,
            size=index_config.chunk_size,
            overlap=index_config.chunk_overlap,
        )

    @staticmethod
    def _build_extract_graph_config(index_config: GraphRagIndexConfig) -> ExtractGraphConfig:
        return ExtractGraphConfig(
            entity_types=index_config.entity_types,
            max_gleanings=index_config.max_gleanings,
        )

    @staticmethod
    def _build_cluster_graph_config(index_config: GraphRagIndexConfig) -> ClusterGraphConfig:
        return ClusterGraphConfig(max_cluster_size=index_config.max_cluster_size)
