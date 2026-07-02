from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, computed_field
from enums import (
    ChunkStrategyEnum,
    DocumentErrorCode,
    DocumentStatusEnum,
    EmbedderProviderEnum,
)
from src.shared.models.base import Entity, ValueObject
from src.shared.models.knowledge_new import (
    BaseSearchConfig,
    CancelRequest,
    FoundChunk,
    GraphSearchConfig,
    IndexRequest,
    NaiveSearchConfig,
    PrechunkRequest,
    PrechunkResponse,
    PreviewChunk,
    SearchConfig,
    SearchRequest,
    SearchResponse,
)

from utils import utcnow

__all__ = [
    "BaseSearchConfig",
    "CancelRequest",
    "ChunkingConfig",
    "Document",
    "EmbeddingConfig",
    "FoundChunk",
    "GraphSearchConfig",
    "IndexRequest",
    "IndexedChunk",
    "NaiveSearchConfig",
    "PrechunkRequest",
    "PrechunkResponse",
    "PreviewChunk",
    "SearchConfig",
    "SearchRequest",
    "SearchResponse",
]


class ChunkingConfig(ValueObject):
    """Parameters controlling how a document is chunked."""

    chunk_strategy: ChunkStrategyEnum
    chunk_size: int
    chunk_overlap: int
    extra: dict = Field(default_factory=dict)


class IndexedChunk(PreviewChunk):
    """A `PreviewChunk` paired with its embedding vector."""

    vector: list[float]


class Document(Entity):
    """A file tracked through chunking and indexing."""

    name: str = Field(frozen=True)
    content: bytes = Field(frozen=True)
    config: ChunkingConfig = Field(frozen=True)
    status: DocumentStatusEnum
    last_indexing_config: ChunkingConfig | None = None
    preview_chunks: list[PreviewChunk] = Field(default_factory=list)
    indexed_chunks: list[IndexedChunk] = Field(default_factory=list)
    error_code: DocumentErrorCode = DocumentErrorCode.NONE
    error_message: str | None = None
    failed_at: datetime | None = None
    completed_at: datetime | None = None

    @computed_field
    def extension(self) -> str:
        return Path(self.name).suffix

    def is_required_reindex(self) -> bool:
        return self.last_indexing_config is not None and self.config != self.last_indexing_config

    def mark_completed(self) -> None:
        self.status = DocumentStatusEnum.COMPLETED
        self.last_indexing_config = self.config.model_copy(deep=True)
        self.completed_at = utcnow()
        self.clear_error()

    def mark_failed(self, error_code: DocumentErrorCode, error_message: str) -> None:
        self.status = DocumentStatusEnum.FAILED
        self.error_code = error_code
        self.error_message = error_message
        self.failed_at = utcnow()
        self.completed_at = None

    def clear_error(self) -> None:
        self.error_code = DocumentErrorCode.NONE
        self.error_message = None
        self.failed_at = None


class EmbeddingConfig(BaseModel):
    """Configuration for an embedding provider client."""

    provider: EmbedderProviderEnum
    api_key: str = Field(exclude=True)
    model: str
    extra: dict = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)
