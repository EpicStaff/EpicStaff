from dataclasses import dataclass, field

from domain.enums import RAGStrategy
from domain.models import FoundChunk, SearchUsage

__all__ = [
    "EmbeddingEstimate",
    "IndexEstimateResult",
    "MetricsResult",
    "Result",
    "SearchResult",
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
