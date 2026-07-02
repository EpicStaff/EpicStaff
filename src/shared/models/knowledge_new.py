from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from src.shared.models.base import ValueObject

from src.shared.enums.knowledge_new import GraphSearchMethodEnum, RAGStrategy

__all__ = [
    "BaseSearchConfig",
    "CancelRequest",
    "FoundChunk",
    "GraphSearchConfig",
    "IndexRequest",
    "NaiveSearchConfig",
    "PrechunkRequest",
    "PrechunkResponse",
    "PreviewChunk",
    "SearchConfig",
    "SearchRequest",
    "SearchResponse",
]


class PreviewChunk(ValueObject):
    """A chunk of text produced before embedding."""

    text: str
    token_count: int | None = None
    overlap_start: int | None = None
    overlap_end: int | None = None


class FoundChunk(ValueObject):
    """A chunk returned from a search, with its ranking metadata."""

    order: int
    similarity: float
    text: str
    source: str = ""


class BaseSearchConfig(BaseModel):
    """Base for search configurations, selected by the `rag_strategy` discriminator."""

    rag_strategy: RAGStrategy
    model_config = ConfigDict(frozen=True)


class NaiveSearchConfig(BaseSearchConfig):
    """Configuration for naive vector-similarity search."""

    rag_strategy: Literal[RAGStrategy.NAIVE] = RAGStrategy.NAIVE
    search_limit: int = 3
    similarity_threshold: float = 0.2


class GraphSearchConfig(BaseSearchConfig):
    """Configuration for graph-based search."""

    rag_strategy: Literal[RAGStrategy.GRAPH] = RAGStrategy.GRAPH
    method: GraphSearchMethodEnum = GraphSearchMethodEnum.BASIC
    prompt: str = ""
    k: int = 10
    max_context_tokens: int = 12_000


SearchConfig = Annotated[GraphSearchConfig | NaiveSearchConfig, Field(discriminator="rag_strategy")]


class PrechunkRequest(ValueObject):
    """Request to pre-chunk a document for a RAG collection."""

    rag_id: int
    rag_strategy: RAGStrategy
    document_id: int


class PrechunkResponse(ValueObject):
    """Preview chunks produced for a `PrechunkRequest`."""

    request: PrechunkRequest
    chunks: list[PreviewChunk]


class IndexRequest(ValueObject):
    """Request to index a RAG collection's documents."""

    rag_id: int
    rag_strategy: RAGStrategy


class SearchRequest(ValueObject):
    """Request to search a RAG collection."""

    rag_id: int
    query: str
    search_config: SearchConfig


class SearchResponse(ValueObject):
    """Chunks matched for a `SearchRequest`."""

    request: SearchRequest
    chunks: list[FoundChunk]


class CancelRequest(ValueObject):
    target_request: dict[str, Any]
