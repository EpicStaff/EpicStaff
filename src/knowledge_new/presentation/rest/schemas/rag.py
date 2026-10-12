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
