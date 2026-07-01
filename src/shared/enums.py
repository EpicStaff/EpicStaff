from enum import StrEnum

__all__ = [
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
