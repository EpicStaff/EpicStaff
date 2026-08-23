from domain.enums import SlotEnum
from domain.models import Rag
from graphrag.config.models.cluster_graph_config import ClusterGraphConfig
from graphrag.config.models.extract_graph_config import ExtractGraphConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_chunking.chunking_config import ChunkingConfig as GraphRagChunkingConfig
from graphrag_input import TextDocument
from graphrag_llm.config import ModelConfig
from infrastructure.database.models import EmbeddingConfig as ORMEmbeddingConfig
from infrastructure.database.models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    LLMConfig,
)
from infrastructure.graphrag.storages import create_storage_config
from infrastructure.graphrag.vector_stores import create_vector_store_config


def _build_completion_model(llm_config: LLMConfig) -> ModelConfig:
    llm_model = llm_config.model

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
        api_key='dummy',
        api_base=llm_model.base_url,
        api_version=llm_model.api_version,
        call_args=call_args,
    )


def _build_embedding_model(embedder_config: ORMEmbeddingConfig) -> ModelConfig:
    embedding_model = embedder_config.model
    return ModelConfig(
        model_provider=embedding_model.embedding_provider.name,
        model=embedding_model.name,
        api_key='dummy',
        api_base=embedding_model.base_url,
    )


def _build_chunking_config(index_config: GraphRagIndexConfig) -> GraphRagChunkingConfig:
    return GraphRagChunkingConfig(
        type=index_config.chunk_strategy,
        size=index_config.chunk_size,
        overlap=index_config.chunk_overlap,
    )


def _build_extract_graph_config(index_config: GraphRagIndexConfig) -> ExtractGraphConfig:
    return ExtractGraphConfig(
        entity_types=index_config.entity_types,
        max_gleanings=index_config.max_gleanings,
    )


def _build_cluster_graph_config(index_config: GraphRagIndexConfig) -> ClusterGraphConfig:
    return ClusterGraphConfig(max_cluster_size=index_config.max_cluster_size)


def graph_rag_orm_to_rag(orm_rag: GraphRag) -> Rag:
    return Rag(
        id=orm_rag.graph_rag_id,
        status=orm_rag.rag_status,
        indexing_document_ids=set(orm_rag.indexing_document_config_ids),
        error_message=orm_rag.error_message,
        outdated_reasons=orm_rag.outdated_reasons or {},
        slot=orm_rag.slot,
    )


def graph_rag_orm_to_graphrag_config(orm_rag: GraphRag, *, slot: SlotEnum) -> GraphRagConfig:
    llm_config: LLMConfig = orm_rag.llm
    embedding_config: ORMEmbeddingConfig = orm_rag.embedder
    index_config: GraphRagIndexConfig = orm_rag.index_config
    return GraphRagConfig(
        completion_models={"default_completion_model": _build_completion_model(llm_config)},
        embedding_models={"default_embedding_model": _build_embedding_model(embedding_config)},
        chunking=_build_chunking_config(index_config),
        extract_graph=_build_extract_graph_config(index_config),
        cluster_graph=_build_cluster_graph_config(index_config),
        input_storage=create_storage_config(rag_id=orm_rag.graph_rag_id, subdir=f"{slot}/input"),
        output_storage=create_storage_config(rag_id=orm_rag.graph_rag_id, subdir=f"{slot}/output"),
        update_output_storage=create_storage_config(
            rag_id=orm_rag.graph_rag_id, subdir=f"{slot}/update_output"
        ),
        vector_store=create_vector_store_config(rag_id=orm_rag.graph_rag_id, subdir=slot),
    )


def graph_document_orm_to_text_document(row: GraphRagDocument, text: str) -> TextDocument:
    document = row.document
    return TextDocument(
        id=str(row.graph_rag_document_id),
        text=text,
        title=document.file_name,
        creation_date=row.created_at.isoformat(),
        raw_data={"status": row.status},
    )


def graph_rag_update_values(rag: Rag) -> dict:
    return {
        "rag_status": rag.status,
        "indexing_document_config_ids": list(rag.indexing_document_ids),
        "error_message": rag.error_message,
        "outdated_reasons": rag.outdated_reasons or {},
        "slot": rag.slot,
    }
