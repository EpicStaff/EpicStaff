from domain.enums import RAGStrategy
from domain.models import ChunkingConfig, FoundChunk, SearchConfig
from presentation.rest.schemas.base import BaseSchema
from pydantic import Field


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


class MetricsOutputSchema(BaseSchema):
    total_chunks: int
    avg_chunk_size: float


class IndexEstimateInputSchema(BaseSchema):
    document_ids: frozenset[int]


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
