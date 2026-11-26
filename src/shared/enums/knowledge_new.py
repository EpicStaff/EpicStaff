from enum import StrEnum

__all__ = [
    "ChunkStrategyEnum",
    "DocumentStatusEnum",
    "GraphOutputTableEnum",
    "GraphSearchMethodEnum",
    "GraphTableSearchScope",
    "RAGStrategy",
]


class RAGStrategy(StrEnum):
    NAIVE = "naive"
    GRAPH = "graph"


class GraphSearchMethodEnum(StrEnum):
    BASIC = "basic"
    LOCAL = "local"
    GLOBAL = "global"
    DRIFT = "drift"


class GraphOutputTableEnum(StrEnum):
    """Tables a graph index run writes to its output storage, named by parquet file stem."""

    ENTITIES = "entities"
    RELATIONSHIPS = "relationships"
    COMMUNITIES = "communities"
    COMMUNITY_REPORTS = "community_reports"
    TEXT_UNITS = "text_units"
    DOCUMENTS = "documents"
    COVARIATES = "covariates"


class GraphTableSearchScope(StrEnum):
    """Scope of the `search` parameter in `/tables/{name}/`.

    `all` (default) matches any user-facing column — the main table's behaviour. `identity`
    restricts matching to each table's identity columns (id + the label the linked-to picker
    shows) so the picker does not surface rows that only match in body text.
    """

    ALL = "all"
    IDENTITY = "identity"


class DocumentStatusEnum(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    CHUNKING = "chunking"  # deprecated
    CHUNKED = "chunked"  # deprecated
    INDEXING = "indexing"  # deprecated
    COMPLETED = "completed"
    WARNING = "warning"  # deprecated
    FAILED = "failed"
    OUTDATED = "outdated"


class ChunkStrategyEnum(StrEnum):
    CHARACTER = "character"
    CSV = "csv"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"
    TOKEN = "token"
