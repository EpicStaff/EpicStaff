import hashlib
import json

from domain.enums import SlotEnum
from domain.errors import GraphRagConfigNotFoundError
from domain.models import EmbeddingConfig, GraphDocument, GraphPricingConfig, Rag
from graphrag.config.models.cluster_graph_config import ClusterGraphConfig
from graphrag.config.models.extract_graph_config import ExtractGraphConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.config.models.reporting_config import ReportingConfig
from graphrag_cache import CacheConfig
from graphrag_chunking.chunking_config import ChunkingConfig as GraphRagChunkingConfig
from graphrag_llm.config import ModelConfig
from graphrag_storage import StorageConfig
from infrastructure.database.models import EmbeddingConfig as ORMEmbeddingConfig
from infrastructure.database.models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    LLMConfig,
)
from infrastructure.graphrag.reporting import PROPAGATE_ONLY_REPORTING
from infrastructure.graphrag.storages import create_storage_config
from infrastructure.graphrag.vector_stores import create_vector_store_config

_SET_BY_REQUEST = "set-by-request"


def _build_completion_model(llm_config: LLMConfig) -> ModelConfig:
    llm_model = llm_config.model
    return _model_config_awaiting_request(llm_model.llm_provider.name, llm_model.name)


def _build_embedding_model(embedder_config: ORMEmbeddingConfig) -> ModelConfig:
    embedding_model = embedder_config.model
    return _model_config_awaiting_request(
        embedding_model.embedding_provider.name, embedding_model.name
    )


def _model_config_awaiting_request(provider: str, model: str) -> ModelConfig:
    # GraphRagConfig validates its models when built, and ModelConfig wants a key and, for
    # Azure, an endpoint. Both arrive with each request, like the settings of the call:
    # apply_request_access replaces these placeholders. Metrics loads this config too, and
    # reads only its storage.
    return ModelConfig(
        model_provider=provider,
        model=model,
        api_key=_SET_BY_REQUEST,
        api_base=_SET_BY_REQUEST,
    )


_ANSWER_CHANGING_MODEL_FIELDS = {"model_provider", "model", "api_base", "api_version"}


def graph_rag_cache_config(rag_id: int, models: list[tuple[ModelConfig, dict]]) -> CacheConfig:
    """Return the cache config for a RAG whose models run with these settings.

    `models` pairs each model with the settings (call arguments) a request runs it with.
    graphrag keys a cached answer on the prompt alone, never on the model or its call
    arguments, so the models and their settings name the cache: changing either starts a
    new one. Cached answers are reused until one changes (graphrag never expires them).
    `call_args` is left out: once a request is applied it also holds the connection secrets
    and headers, and a key rotation must keep the cache.
    """
    settings_json = json.dumps(
        [
            {
                **model.model_dump(mode="json", include=_ANSWER_CHANGING_MODEL_FIELDS),
                "settings": settings,
            }
            for model, settings in models
        ],
        sort_keys=True,
    )
    # Per RAG, not per slot, so a reindex into the other slot reuses the answers. graphrag's
    # defaults put the cache and the logs under the working directory, which is read-only.
    return CacheConfig(
        type="json",
        storage=create_storage_config(
            rag_id=rag_id,
            subdir="cache/" + hashlib.sha256(settings_json.encode()).hexdigest()[:16],
        ),
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


def graph_rag_output_storage_config(rag_id: int, *, slot: SlotEnum) -> StorageConfig:
    """Return the storage config where `slot`'s index run writes its output tables."""
    return create_storage_config(rag_id=rag_id, subdir=f"{slot}/output")


def graph_rag_orm_to_graphrag_config(orm_rag: GraphRag, *, slot: SlotEnum) -> GraphRagConfig:
    llm_config: LLMConfig = orm_rag.llm
    embedding_config: ORMEmbeddingConfig = orm_rag.embedder
    index_config: GraphRagIndexConfig = orm_rag.index_config
    completion_model = _build_completion_model(llm_config)
    embedding_model = _build_embedding_model(embedding_config)
    return GraphRagConfig(
        completion_models={"default_completion_model": completion_model},
        embedding_models={"default_embedding_model": embedding_model},
        chunking=_build_chunking_config(index_config),
        extract_graph=_build_extract_graph_config(index_config),
        cluster_graph=_build_cluster_graph_config(index_config),
        input_storage=create_storage_config(rag_id=orm_rag.graph_rag_id, subdir=f"{slot}/input"),
        output_storage=graph_rag_output_storage_config(orm_rag.graph_rag_id, slot=slot),
        update_output_storage=create_storage_config(
            rag_id=orm_rag.graph_rag_id, subdir=f"{slot}/update_output"
        ),
        vector_store=create_vector_store_config(rag_id=orm_rag.graph_rag_id, subdir=slot),
        # Named by the models alone until a request brings their settings and endpoints:
        # the orchestrators name it again after `apply_request_access`.
        cache=graph_rag_cache_config(
            orm_rag.graph_rag_id, [(completion_model, {}), (embedding_model, {})]
        ),
        reporting=ReportingConfig(type=PROPAGATE_ONLY_REPORTING),
    )


def graph_document_orm_to_graph_document(row: GraphRagDocument) -> GraphDocument:
    document = row.document
    return GraphDocument(
        id=row.graph_rag_document_id,
        name=document.file_name,
        extension=f".{document.file_type}",
        content_key=document.document_content.object_key,
        created_at=row.created_at,
        status=row.status,
    )


def graph_rag_update_values(rag: Rag) -> dict:
    return {
        "rag_status": rag.status,
        "indexing_document_config_ids": list(rag.indexing_document_ids),
        "error_message": rag.error_message,
        "outdated_reasons": rag.outdated_reasons or {},
        "slot": rag.slot,
    }


def graph_rag_orm_to_pricing_config(orm_rag: GraphRag) -> GraphPricingConfig:
    """Map a GraphRag with its relations loaded to the config needed to price its usage.

    Raises:
        GraphRagConfigNotFoundError: If the LLM or embedder has no model or provider set.
    """
    llm_config: LLMConfig = orm_rag.llm
    llm_model = llm_config.model
    embedding_model = orm_rag.embedder.model
    if (
        llm_model is None
        or llm_model.llm_provider is None
        or embedding_model is None
        or embedding_model.embedding_provider is None
    ):
        raise GraphRagConfigNotFoundError(rag_id=orm_rag.graph_rag_id)
    return GraphPricingConfig(
        embedding=EmbeddingConfig(
            provider=embedding_model.embedding_provider.name.lower(),
            model=embedding_model.name,
        ),
        llm_provider=llm_model.llm_provider.name.lower(),
        llm_model=llm_model.name,
        input_cost_per_token=llm_config.input_cost_per_token,
        output_cost_per_token=llm_config.output_cost_per_token,
    )
