from dataclasses import dataclass, field

from domain.enums import RAGStrategy
from domain.models import FoundChunk, SearchUsage

__all__ = [
    "EmbeddingEstimate",
    "GraphVisualizationResult",
    "IndexEstimateResult",
    "MetricsResult",
    "Result",
    "SearchResult",
    "VisualizationCommunity",
    "VisualizationEntity",
    "VisualizationRelationship",
]


@dataclass(frozen=True)
class Result:
    pass


@dataclass(frozen=True)
class SearchResult(Result):
    result: list[FoundChunk] | str
    usage: SearchUsage = field(default_factory=SearchUsage)


@dataclass(frozen=True)
class PrechunkResult:
    rag_id: int
    document_id: int
    chunk_count: int


@dataclass(frozen=True)
class MetricsResult(Result):
    total_chunks: int
    avg_chunk_size: float


@dataclass(frozen=True)
class VisualizationEntity:
    id: str
    title: str
    type: str | None
    description: str | None
    degree: int
    community_ids: list[str]


@dataclass(frozen=True)
class VisualizationRelationship:
    id: str
    source: str
    target: str
    description: str | None
    weight: float


@dataclass(frozen=True)
class VisualizationCommunity:
    id: str
    title: str
    level: int
    size: int
    entity_ids: list[str]


@dataclass(frozen=True)
class GraphVisualizationResult(Result):
    entities: list[VisualizationEntity]
    relationships: list[VisualizationRelationship]
    communities: list[VisualizationCommunity]


@dataclass(frozen=True)
class EmbeddingEstimate:
    tokens: int
    exact: bool
    cost_usd: float | None


@dataclass(frozen=True)
class IndexEstimateResult(Result):
    rag_type: RAGStrategy
    document_count: int
    chunk_count: int
    embedding: EmbeddingEstimate
