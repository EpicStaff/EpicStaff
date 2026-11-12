from domain.enums import RAGStrategy
from domain.models import ChunkingConfig, FoundChunk, SearchConfig, SearchUsage
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
    usage: SearchUsage = Field(default_factory=SearchUsage)


class MetricsOutputSchema(BaseSchema):
    total_chunks: int
    avg_chunk_size: float


class DocumentChunkingOverrideSchema(BaseSchema):
    document_id: int
    chunking_config: ChunkingConfig


class VisualizationEntitySchema(BaseSchema):
    id: str
    title: str
    type: str | None
    degree: int
    community_ids: list[str]


class VisualizationRelationshipSchema(BaseSchema):
    id: str
    source: str
    target: str
    weight: float


class GraphVisualizationOutputSchema(BaseSchema):
    entities: list[VisualizationEntitySchema]
    relationships: list[VisualizationRelationshipSchema]
    total_entities: int
    total_relationships: int


class EntityDetailOutputSchema(BaseSchema):
    description: str | None


class RelationshipDetailOutputSchema(BaseSchema):
    description: str | None


class GraphTableDataOutputSchema(BaseSchema):
    columns: list[str]
    rows: list[dict[str, object]]
    total: int
    page: int
    page_size: int


class IndexEstimateInputSchema(BaseSchema):
    document_ids: frozenset[int]
    chunking_overrides: list[DocumentChunkingOverrideSchema] = Field(default_factory=list)


class EmbeddingEstimateSchema(BaseSchema):
    tokens: int
    exact: bool
    cost_usd: float | None


class IndexEstimateOutputSchema(BaseSchema):
    rag_type: RAGStrategy
    document_count: int
    chunk_count: int
    embedding: EmbeddingEstimateSchema
