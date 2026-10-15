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
from loguru import logger
from src.shared.models.ai_providers import LLMConfigData

# GraphRAG never sends an LLM config's stop sequences or timeout. Stop sequences written
# for agents would cut extraction output short, and the config's timeout (120 s by
# default) would abort long extraction and community-report calls.
_GRAPHRAG_EXCLUDED_GENERATION_FIELDS = {"stop", "timeout"}


def _parse_logit_bias(llm_config: LLMConfig) -> dict[int, float] | None:
    """Return the config's logit_bias with integer token ids, or None if it is malformed.

    The column is JSON, so token ids arrive as string keys. A key or value that is not
    numeric is dropped with a warning instead of failing the whole GraphRAG config.
    """
    raw_logit_bias = llm_config.logit_bias
    if not raw_logit_bias:
        return None
    try:
        return {int(token_id): float(bias) for token_id, bias in raw_logit_bias.items()}
    except (AttributeError, TypeError, ValueError):
        logger.warning(
            "Ignoring malformed logit_bias on LLM config {}: {!r}",
            llm_config.id,
            raw_logit_bias,
        )
        return None


def _build_completion_model(llm_config: LLMConfig) -> ModelConfig:
    llm_model = llm_config.model
    provider = llm_model.llm_provider.name
    # stop and timeout are left out here as well as excluded below: stop is unvalidated
    # JSON, and a value GraphRAG discards must not be able to fail the config build.
    llm_config_data = LLMConfigData(
        model=llm_model.name,
        temperature=llm_config.temperature,
        top_p=llm_config.top_p,
        max_tokens=llm_config.max_tokens,
        presence_penalty=llm_config.presence_penalty,
        frequency_penalty=llm_config.frequency_penalty,
        logit_bias=_parse_logit_bias(llm_config),
        seed=llm_config.seed,
        reasoning_effort=llm_config.reasoning_effort,
    )

    return ModelConfig(
        model_provider=provider,
        model=llm_model.name,
        api_key="dummy",
        api_base=llm_model.base_url,
        api_version=llm_model.api_version,
        call_args=llm_config_data.to_litellm_kwargs(
            provider=provider, exclude=_GRAPHRAG_EXCLUDED_GENERATION_FIELDS
        ),
    )


def _build_embedding_model(embedder_config: ORMEmbeddingConfig) -> ModelConfig:
    embedding_model = embedder_config.model
    return ModelConfig(
        model_provider=embedding_model.embedding_provider.name,
        model=embedding_model.name,
        api_key="dummy",
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
