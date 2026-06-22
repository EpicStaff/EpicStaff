from pathlib import Path
from typing import (
    Any,
    Optional,
    Literal,
    Annotated,
    Union,
)

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    ConfigDict,
)

from enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    RAGStrategy,
    GraphSearchMethodEnum,
)

__all__ = [
    "ValueObject",
    "Entity",
    "ChunkingConfig",
    "PreviewChunk",
    "IndexedChunk",
    "FoundChunk",
    "Document",
    "EmbeddingConfig",
    "BaseSearchConfig",
    "NaiveSearchConfig",
    "GraphSearchConfig",
    "SearchConfig",
    "PrechunkRequest",
    "PrechunkResponse",
    "IndexRequest",
    "SearchRequest",
    "SearchResponse",
]


class ValueObject(BaseModel):
    """Base for immutable value objects — frozen after creation and compared by value."""

    model_config = ConfigDict(frozen=True)


class Entity(BaseModel):
    """Base for domain entities identified by a stable `id`."""

    id: Any = Field(frozen=True)

    model_config = ConfigDict(validate_assignment=True)


class ChunkingConfig(ValueObject):
    """Parameters controlling how a document is chunked."""

    chunk_strategy: ChunkStrategyEnum
    chunk_size: int
    chunk_overlap: int
    extra: dict = Field(default_factory=dict)


class PreviewChunk(ValueObject):
    """A chunk of text produced before embedding."""

    text: str
    token_count: Optional[int] = None
    overlap_start: Optional[int] = None
    overlap_end: Optional[int] = None


class IndexedChunk(PreviewChunk):
    """A `PreviewChunk` paired with its embedding vector."""

    vector: list[float]


class FoundChunk(ValueObject):
    """A chunk returned from a search, with its ranking metadata."""

    order: int
    similarity: float
    text: str
    source: str = ""


class Document(Entity):
    """A file tracked through chunking and indexing."""

    name: str = Field(frozen=True)
    content: bytes = Field(frozen=True)
    config: ChunkingConfig = Field(frozen=True)
    status: DocumentStatusEnum
    preview_chunks: list[PreviewChunk] = Field(default_factory=list)
    indexed_chunks: list[IndexedChunk] = Field(default_factory=list)

    @computed_field
    def extension(self) -> str:
        return Path(self.name).suffix


class EmbeddingConfig(BaseModel):
    """Configuration for an embedding provider client."""

    provider: EmbedderProviderEnum
    api_key: str = Field(exclude=True)
    model: str
    extra: dict = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


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


SearchConfig = Annotated[
    Union[GraphSearchConfig, NaiveSearchConfig],
    Field(discriminator="rag_strategy"),
]


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
