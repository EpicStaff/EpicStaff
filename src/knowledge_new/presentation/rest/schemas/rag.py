from domain.enums import RAGStrategy
from domain.models import ChunkingConfig, FoundChunk, SearchConfig, SearchUsage
from presentation.rest.schemas.base import BaseSchema
from pydantic import ConfigDict, Field


class IndexInputSchema(BaseSchema):
    document_ids: frozenset[int]
    embedding_api_key: str
    llm_api_key: str | None = None
    embedding_extra_headers: dict[str, str] = Field(default_factory=dict)
    llm_extra_headers: dict[str, str] = Field(default_factory=dict)


class PrechunkInputSchema(BaseSchema):
    document_id: int
    chunking_config: ChunkingConfig


class PrechunkOutputSchema(BaseSchema):
    rag_id: int
    document_id: int
    chunk_count: int


class SearchInputSchema(BaseSchema):
    query: str
    search_config: SearchConfig
    embedding_api_key: str
    llm_api_key: str | None = None
    embedding_extra_headers: dict[str, str] = Field(default_factory=dict)
    llm_extra_headers: dict[str, str] = Field(default_factory=dict)


class SearchOutputSchema(BaseSchema):
    result: list[FoundChunk] | str
    usage: SearchUsage = Field(default_factory=SearchUsage)


class MetricsOutputSchema(BaseSchema):
    total_chunks: int
    avg_chunk_size: float


class IndexConfigOverridesSchema(BaseSchema):
    """Unsaved GraphRAG index settings an indexing estimate is computed with.

    Sent by django_app; each set field replaces the stored value for the estimate only.
    Only the settings that change the estimate are accepted, and any other key is
    rejected, so the caller must forward exactly these fields.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True, extra="forbid")

    chunk_size: int | None = None
    chunk_overlap: int | None = None
    max_gleanings: int | None = None


class IndexEstimateInputSchema(BaseSchema):
    document_ids: frozenset[int]
    index_config: IndexConfigOverridesSchema | None = None


class EmbeddingEstimateSchema(BaseSchema):
    tokens: int
    exact: bool
    cost_usd: float | None


class LlmEstimateSchema(BaseSchema):
    calls: int
    tokens_min: int
    tokens_max: int
    cost_usd_min: float | None
    cost_usd_max: float | None


class IndexEstimateOutputSchema(BaseSchema):
    rag_type: RAGStrategy
    document_count: int
    chunk_count: int
    embedding: EmbeddingEstimateSchema
    llm: LlmEstimateSchema | None
