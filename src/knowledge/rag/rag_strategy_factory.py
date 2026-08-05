from rag.base_rag_strategy import BaseRAGStrategy
from rag.naive_rag_strategy import NaiveRAGStrategy
from rag.graph_rag.graph_rag_strategy import GraphRAGStrategy


class RAGStrategyFactory:
    """Factory for selecting correct RAG strategy by type."""

    _strategies: dict[str, BaseRAGStrategy] = {
        "naive": NaiveRAGStrategy(),
    }

    @classmethod
    def get_strategy(cls, rag_type: str):
        if rag_type == "graph" and rag_type not in cls._strategies:
            cls._strategies[rag_type] = GraphRAGStrategy()

        if rag_type not in cls._strategies:
            raise ValueError(f"Unsupported RAG type: {rag_type}")

        return cls._strategies[rag_type]
