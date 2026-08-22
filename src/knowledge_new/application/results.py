from dataclasses import dataclass

from domain.models import FoundChunk

__all__ = [
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
