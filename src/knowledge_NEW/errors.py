from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from chunkers import AbstractChunker
    from file_text_extractors import AbstractFileTextExtractor


__all__ = [
    "KnowledgeError",
    "UnsupportedError",
    "FileTextExtractingError",
    "ChunkingError",
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
