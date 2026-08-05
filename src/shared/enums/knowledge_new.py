from enum import StrEnum

__all__ = [
    "DocumentStatusEnum",
    "GraphSearchMethodEnum",
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
