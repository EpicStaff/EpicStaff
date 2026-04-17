from rag.naive_rag_strategy import NaiveRAGStrategy
from rag.graph_rag.graph_rag_strategy import GraphRAGStrategy


class RAGStrategyFactory:
    """Factory for selecting correct RAG strategy by type."""

    _strategies = {
        "naive": NaiveRAGStrategy(),
        "graph": GraphRAGStrategy(),
    }

    @classmethod
    def get_strategy(cls, rag_type: str):
        if rag_type not in cls._strategies:
            raise ValueError(f"Unsupported RAG type: {rag_type}")
        return cls._strategies[rag_type]
