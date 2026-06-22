from pathlib import Path
from typing import (
    Any,
    Optional,
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
)

__all__ = [
    "ValueObject",
    "Entity",
    "ChunkingConfig",
    "PreviewChunk",
    "Document",
    "EmbeddingConfig",
    "PrechunkRequest",
    "PrechunkResponse",
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


class Document(Entity):
    """A file tracked through chunking and indexing."""

    name: str = Field(frozen=True)
    content: bytes = Field(frozen=True)
    config: ChunkingConfig = Field(frozen=True)
    status: DocumentStatusEnum
    preview_chunks: list[PreviewChunk] = Field(default_factory=list)

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


class PrechunkRequest(ValueObject):
    """Request to pre-chunk a document for a RAG collection."""

    rag_id: int
    rag_strategy: RAGStrategy
    document_id: int


class PrechunkResponse(ValueObject):
    """Preview chunks produced for a `PrechunkRequest`."""

    request: PrechunkRequest
    chunks: list[PreviewChunk]
