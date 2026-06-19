from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from chunkers import AbstractChunker


__all__ = [
    "KnowledgeError",
    "UnsupportedError",
    "ChunkingError",
]


class KnowledgeError(Exception):
    """Base error for all domain errors."""


class UnsupportedError(KnowledgeError):
    def __init__(self, that: str, got: Any):
        super().__init__(f"Unsupported {that}: '{got!r}'")


class ChunkingError(KnowledgeError):
    def __init__(self, text: str, chunker: AbstractChunker):
        super().__init__(f"Cannot chunk the text '{text}' by {type(chunker).__name__}.")
