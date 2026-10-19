from dataclasses import dataclass, field

from domain.models import ChunkingConfig, SearchConfig

__all__ = [
    "Command",
    "GetIndexEstimate",
    "GetMetrics",
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
    # Provider keys stay out of repr, so logging a command never writes them in cleartext.
    embedding_api_key: str = field(repr=False)
    llm_api_key: str | None = field(default=None, repr=False)
    # Resolved header values can carry credentials; repr=False keeps them out of logs.
    embedding_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    llm_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class RunSearch(Command):
    rag_id: int
    query: str
    search_config: SearchConfig
    # Provider keys stay out of repr, so logging a command never writes them in cleartext.
    embedding_api_key: str = field(repr=False)
    llm_api_key: str | None = field(default=None, repr=False)
    # Resolved header values can carry credentials; repr=False keeps them out of logs.
    embedding_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    llm_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class RunPrechunk(Command):
    rag_id: int
    document_id: int
    chunking_config: ChunkingConfig


@dataclass(frozen=True)
class RemoveRag(Command):
    rag_id: int


@dataclass(frozen=True)
class GetMetrics(Command):
    rag_id: int


@dataclass(frozen=True)
class GetIndexEstimate(Command):
    rag_id: int
    document_ids: frozenset[int]
