from dataclasses import dataclass, field

from domain.enums import RAGStrategy
from domain.models import FoundChunk, SearchUsage

__all__ = [
    "EmbeddingEstimate",
    "EntityDetailResult",
    "GraphTableDataResult",
    "GraphTableSummaryItem",
    "GraphTableSummaryResult",
    "GraphVisualizationResult",
    "IndexEstimateResult",
    "MetricsResult",
    "RelationshipDetailResult",
    "Result",
    "SearchResult",
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
    degree: int
    community_ids: list[str]


@dataclass(frozen=True)
class VisualizationRelationship:
    id: str
    source: str
    target: str
    weight: float


@dataclass(frozen=True)
class GraphTableDataResult(Result):
    columns: list[str]
    rows: list[dict[str, object]]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class GraphTableSummaryItem:
    name: str
    label: str
    count: int


@dataclass(frozen=True)
class GraphTableSummaryResult(Result):
    tables: list[GraphTableSummaryItem]


@dataclass(frozen=True)
class GraphVisualizationResult(Result):
    entities: list[VisualizationEntity]
    relationships: list[VisualizationRelationship]
    total_entities: int
    total_relationships: int


@dataclass(frozen=True)
class EntityDetailResult(Result):
    description: str | None


@dataclass(frozen=True)
class RelationshipDetailResult(Result):
    description: str | None


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
