from dataclasses import dataclass

from domain.enums import RAGStrategy
from domain.models import FoundChunk

__all__ = [
    "EmbeddingEstimate",
    "IndexEstimateResult",
    "LlmEstimate",
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
class LlmEstimate:
    calls: int
    tokens_min: int
    tokens_max: int
    cost_usd_min: float | None
    cost_usd_max: float | None


@dataclass(frozen=True)
class IndexEstimateResult(Result):
    rag_type: RAGStrategy
    document_count: int
    chunk_count: int
    embedding: EmbeddingEstimate
    llm: LlmEstimate | None = None
