from dataclasses import dataclass, field

from domain.models import ChunkingConfig, GraphEstimateOverrides, SearchConfig

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
    embedding_api_key: str
    llm_api_key: str | None = field(default=None)
    # Resolved header values can carry credentials; repr=False keeps them out of logs.
    embedding_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    llm_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class RunSearch(Command):
    rag_id: int
    query: str
    search_config: SearchConfig
    embedding_api_key: str
    llm_api_key: str | None = field(default=None)
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
    index_config: GraphEstimateOverrides | None = None
