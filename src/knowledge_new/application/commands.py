from dataclasses import dataclass

from domain.models import ChunkingConfig, SearchConfig

__all__ = [
    "Command",
    "RunIndex",
    "RunPrechunk",
    "RunSearch",
]


@dataclass(frozen=True)
class Command:
    pass


@dataclass(frozen=True)
class RunIndex(Command):
    rag_id: int
    document_ids: frozenset[int]


@dataclass(frozen=True)
class RunSearch(Command):
    rag_id: int
    query: str
    search_config: SearchConfig


@dataclass(frozen=True)
class RunPrechunk(Command):
    rag_id: int
    document_id: int
    chunking_config: ChunkingConfig
