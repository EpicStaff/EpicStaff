from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
)

from enums import (
    ChunkStrategyEnum,
    EmbedderProviderEnum,
)

__all__ = [
    "ValueObject",
    "Entity",
    "ChunkingConfig",
    "PreviewChunk",
    "EmbeddingConfig",
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


class EmbeddingConfig(BaseModel):
    """Configuration for an embedding provider client."""

    provider: EmbedderProviderEnum
    api_key: str = Field(exclude=True)
    model: str
    extra: dict = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)
