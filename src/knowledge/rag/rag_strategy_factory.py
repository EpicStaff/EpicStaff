from rag.base_rag_strategy import BaseRAGStrategy
from rag.naive_rag_strategy import NaiveRAGStrategy
from utils.cpu_features import supports_avx2


class GraphRAGUnavailableError(RuntimeError):
    """Raised when GraphRAG is requested on a host that can't run it."""


class RAGStrategyFactory:
    """Factory for selecting correct RAG strategy by type."""

    _strategies: dict[str, BaseRAGStrategy] = {
        "naive": NaiveRAGStrategy(),
    }

    @classmethod
    def get_strategy(cls, rag_type: str):
        if rag_type == "graph" and rag_type not in cls._strategies:
            cls._strategies[rag_type] = cls._create_graph_rag_strategy()

        if rag_type not in cls._strategies:
            raise ValueError(f"Unsupported RAG type: {rag_type}")

        return cls._strategies[rag_type]

    @staticmethod
    def _create_graph_rag_strategy():
        if not supports_avx2():
            raise GraphRAGUnavailableError(
                "GraphRAG is unavailable: this host's CPU lacks AVX2 support required by lancedb."
            )

        from rag.graph_rag.graph_rag_strategy import GraphRAGStrategy

        return GraphRAGStrategy()
