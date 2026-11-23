from collections.abc import Mapping
from dataclasses import dataclass, field

from application.graph_index_read_limits import (
    GRAPH_TABLE_DEFAULT_PAGE,
    GRAPH_TABLE_DEFAULT_PAGE_SIZE,
    GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES,
)
from domain.enums import GraphOutputTableEnum, GraphTableSearchScope
from domain.models import ChunkingConfig, SearchConfig

__all__ = [
    "Command",
    "ExportGraphArtifacts",
    "GetEntityDetail",
    "GetGraphTableData",
    "GetGraphTableSummary",
    "GetGraphVisualization",
    "GetIndexEstimate",
    "GetMetrics",
    "GetRelationshipDetail",
    "RemoveRag",
    "RestoreGraphArtifacts",
    "RewriteGraphDocumentIds",
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
class GetGraphVisualization(Command):
    """Request for one page of a paginated graph visualization.

    The pool the slice is taken from is `max_entities * page_count` top entities; the
    response returns the `page`-th slice of that pool and its share of the pool's edges.
    The default (page=0, page_count=1) reproduces a single whole-pool request.
    """

    rag_id: int
    max_entities: int = GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES
    search: str | None = None
    page: int = 0
    page_count: int = 1

    def __post_init__(self) -> None:
        if self.page_count < 1:
            raise ValueError("page_count must be at least 1.")
        if self.page < 0 or self.page >= self.page_count:
            raise ValueError(
                f"page must be in [0, page_count) (got page={self.page}, page_count={self.page_count})."
            )


@dataclass(frozen=True)
class GetGraphTableData(Command):
    rag_id: int
    table_name: str
    page: int = GRAPH_TABLE_DEFAULT_PAGE
    page_size: int = GRAPH_TABLE_DEFAULT_PAGE_SIZE
    search: str | None = None
    # Which columns `search` matches against. `ALL` (default) keeps the main table's
    # behaviour — any user-facing column. `IDENTITY` narrows to id + the per-table label
    # column(s), used by the linked-to picker so the list is not polluted by body-text hits.
    search_scope: GraphTableSearchScope = GraphTableSearchScope.ALL
    # Optional exact-match filter on a single column. Both filter_column and
    # filter_value must be set together; the match is applied before `search`.
    filter_column: str | None = None
    filter_value: str | None = None
    # Optional graph-relation filter: keep rows linked to a row of another table.
    # Both parts must be sent together; the relation is resolved through the graph
    # index. Only pairs listed in link_resolver.ALLOWED_PAIRS are supported — every
    # other (subject, target) pair raises UnsupportedError (400).
    linked_to_type: GraphOutputTableEnum | None = None
    linked_to_id: str | None = None

    def __post_init__(self) -> None:
        if (self.linked_to_type is None) != (self.linked_to_id is None):
            raise ValueError("linked_to_type and linked_to_id must be set together.")


@dataclass(frozen=True)
class GetGraphTableSummary(Command):
    rag_id: int


@dataclass(frozen=True)
class GetEntityDetail(Command):
    rag_id: int
    entity_id: str


@dataclass(frozen=True)
class GetRelationshipDetail(Command):
    rag_id: int
    relationship_id: str


@dataclass(frozen=True)
class GetIndexEstimate(Command):
    rag_id: int
    document_ids: frozenset[int]
    # Chunking settings the user has not saved yet, by document id; they replace the stored ones.
    chunking_overrides: dict[int, ChunkingConfig] = field(default_factory=dict)


# GraphRAG artifact transfer (export, restore, document id rewrite)
@dataclass(frozen=True)
class ExportGraphArtifacts(Command):
    rag_id: int


@dataclass(frozen=True)
class RestoreGraphArtifacts(Command):
    rag_id: int
    archive_path: str


@dataclass(frozen=True)
class RewriteGraphDocumentIds(Command):
    rag_id: int
    document_id_map: Mapping[str, int]
