from datetime import datetime
from pathlib import Path
from typing import Optional

from enums import (
    ChunkStrategyEnum,
    DocumentErrorCode,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
)
from pydantic import Field, computed_field
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
    "Rag",
    "SearchConfig",
    "SearchRequest",
    "SearchResponse",
]


class Rag(Entity):
    status: IndexStatusEnum
    indexing_document_ids: set[int]

    def finish_document(self, document_id: int):
        self.indexing_document_ids.discard(document_id)

    def finish(self, has_completed_document: bool, has_failed_document: bool):
        if not has_completed_document:
            self.status = IndexStatusEnum.FAILED
        elif has_failed_document:
            self.status = IndexStatusEnum.WARNING
        else:
            self.status = IndexStatusEnum.COMPLETED
        self.indexing_document_ids.clear()

    def mark_as_processing(self, document_ids: frozenset[int]):
        self.status = IndexStatusEnum.PROCESSING
        self.indexing_document_ids.update(document_ids)

    def mark_as_cancelled(self):
        self.status = IndexStatusEnum.CANCELLED
        self.indexing_document_ids.clear()

    def mark_as_failed(self):
        self.status = IndexStatusEnum.FAILED
        self.indexing_document_ids.clear()


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

    def mark_failed(self, error: Optional[Exception] = None) -> None:
        self.status = DocumentStatusEnum.FAILED
        self.error_message = f'{type(error).__name__}: {error}'
        self.failed_at = utcnow()
        self.completed_at = None

    def clear_error(self) -> None:
        self.error_code = DocumentErrorCode.NONE
        self.error_message = None
        self.failed_at = None


class EmbeddingConfig(ValueObject):
    """Configuration for an embedding provider client."""

    provider: EmbedderProviderEnum
    api_key: str = Field(exclude=True)
    model: str
    extra: dict = Field(default_factory=dict)
