from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from chunkers import AbstractChunker
    from embedders import AbstractEmbedder
    from file_text_extractors import AbstractFileTextExtractor


__all__ = [
    "KnowledgeError",
    "UnsupportedError",
    "FileTextExtractingError",
    "ChunkingError",
    "EmbeddingError",
    "DocumentNotFound",
    "EmbedderUnavailableError",
]


class KnowledgeError(Exception):
    """Base error for all domain errors."""


class UnsupportedError(KnowledgeError):
    def __init__(self, that: str, got: Any):
        super().__init__(f"Unsupported {that}: '{got!r}'")


class FileTextExtractingError(KnowledgeError):
    def __init__(self, extractor: AbstractFileTextExtractor):
        super().__init__(
            f"Cannot extract the text from binary by {type(extractor).__name__}."
        )


class ChunkingError(KnowledgeError):
    def __init__(self, text: str, chunker: AbstractChunker):
        super().__init__(f"Cannot chunk the text '{text}' by {type(chunker).__name__}.")


class EmbeddingError(KnowledgeError):
    def __init__(self, text: str, embedder: AbstractEmbedder):
        super().__init__(
            f"Cannot embed the text: '{text}' by {type(embedder).__name__}."
        )


class DocumentNotFound(KnowledgeError):
    pass


class EmbedderUnavailableError(KnowledgeError):
    pass
