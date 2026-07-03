from enum import StrEnum

__all__ = [
    "GraphSearchMethodEnum",
    "RAGStrategy",
    "DocumentStatusEnum",
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
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    INDEXING = "indexing"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"
