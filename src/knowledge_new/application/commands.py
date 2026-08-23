from dataclasses import dataclass, field

from domain.models import ChunkingConfig, SearchConfig

__all__ = [
    "Command",
    "RemoveRag",
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
    embedding_api_key: str
    llm_api_key: str | None = field(default=None)


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


@dataclass(frozen=True)
class RemoveRag(Command):
    rag_id: int
