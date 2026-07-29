from collections.abc import Iterable
from pathlib import Path

from enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
)
from pydantic import Field, computed_field
from src.shared.models.base import Entity, ValueObject
from src.shared.models.knowledge_new import (
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

__all__ = [
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
    error_message: str | None = None
    reindex_reason: dict[str, str] = Field(default_factory=dict)

    def finish_document(self, document_id: int):
        self.indexing_document_ids.discard(document_id)

    def mark_as_processing(self, document_ids: Iterable[int]):
        self.status = IndexStatusEnum.PROCESSING
        self.indexing_document_ids.update(document_ids)
        self.error_message = None

    def mark_as_completed(self):
        self.status = IndexStatusEnum.COMPLETED
        self.indexing_document_ids.clear()
        self.reindex_reason.clear()

    def mark_as_failed(self, error: Exception | str):
        self.status = IndexStatusEnum.FAILED
        self.error_message = str(error)
        self.indexing_document_ids.clear()

    def mark_as_warning(self):
        self.status = IndexStatusEnum.WARNING
        self.indexing_document_ids.clear()

    def mark_as_cancelled(self):
        self.status = IndexStatusEnum.CANCELLED
        self.indexing_document_ids.clear()
        self.error_message = None


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
    last_indexing_config: ChunkingConfig | None = None
    status: DocumentStatusEnum
    preview_chunks: list[PreviewChunk] = Field(default_factory=list)
    indexed_chunks: list[IndexedChunk] = Field(default_factory=list)
    error_message: str | None = None

    @computed_field
    def extension(self) -> str:
        return Path(self.name).suffix

    def has_config_changed(self) -> bool:
        return (
            self.last_indexing_config is not None
            and self.config != self.last_indexing_config
        )

    def mark_as_processing(self):
        self.status = DocumentStatusEnum.PROCESSING
        self.error_message = None

    def mark_as_chunking(self):
        self.status = DocumentStatusEnum.CHUNKING

    def mark_as_chunked(self, chunks: list[PreviewChunk]):
        self.status = DocumentStatusEnum.CHUNKED
        self.preview_chunks = chunks

    def mark_as_indexing(self):
        self.status = DocumentStatusEnum.INDEXING

    def mark_as_completed(self, chunks: list[IndexedChunk]):
        self.status = DocumentStatusEnum.COMPLETED
        self.preview_chunks = []
        self.indexed_chunks = chunks
        self.last_indexing_config = self.config.model_copy(deep=True)

    def mark_as_failed(self, error: Exception | str):
        self.status = DocumentStatusEnum.FAILED
        self.error_message = str(error)


class EmbeddingConfig(ValueObject):
    """Configuration for an embedding provider client."""

    provider: EmbedderProviderEnum
    api_key: str = Field(exclude=True)
    model: str
    extra: dict = Field(default_factory=dict)
