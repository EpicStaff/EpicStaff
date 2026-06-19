from typing import Any


__all__ = [
    "KnowledgeError",
    "UnsupportedError",
]


class KnowledgeError(Exception):
    """Base error for all domain errors."""


class UnsupportedError(KnowledgeError):
    def __init__(self, that: str, got: Any):
        super().__init__(f"Unsupported {that}: '{got!r}'")
