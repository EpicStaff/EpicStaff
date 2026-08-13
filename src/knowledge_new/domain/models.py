from collections.abc import Iterable
from pathlib import Path

from domain.enums import (
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
)
from pydantic import Field, computed_field
from src.shared.models.base import Entity, ValueObject
from src.shared.models.knowledge_new import (
    CancelRequest,
    ChunkingConfig,
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
    outdated_reasons: dict[str, str] = Field(default_factory=dict)

    def finish_document(self, *ids: int):
        self.indexing_document_ids.difference_update(ids)

    def mark_as_new(self):
        self.status = IndexStatusEnum.NEW
        self.error_message = None
        self.outdated_reasons.clear()

    def mark_as_processing(self, document_ids: Iterable[int]):
        self.status = IndexStatusEnum.PROCESSING
        self.indexing_document_ids.update(document_ids)
        self.error_message = None

    def mark_as_completed(self):
        self.status = IndexStatusEnum.COMPLETED

    def mark_as_failed(self, error: Exception | str):
        self.status = IndexStatusEnum.FAILED
        if isinstance(error, BaseExceptionGroup):
            sub_details = "; ".join(f"{type(e).__name__}: {e}" for e in error.exceptions)
            self.error_message = (
                f"{error.message} [{sub_details}]" if sub_details else error.message
            )
        else:
            self.error_message = str(error)

    def mark_as_outdated(self, **reasons: str):
        self.status = IndexStatusEnum.OUTDATED
        self.outdated_reasons.update(reasons)

    def mark_as_partial(self):
        self.status = IndexStatusEnum.PARTIAL

    def mark_as_cancelled(self):
        self.status = IndexStatusEnum.CANCELLED
        self.error_message = None


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
        return self.last_indexing_config is not None and self.config != self.last_indexing_config

    def mark_as_processing(self):
        self.status = DocumentStatusEnum.PROCESSING
        self.error_message = None

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
