"""Factory for building document indexers from a RAG strategy."""

from enums import RAGStrategy
from errors import UnsupportedError
from orchestrators.indexing.base import AbstractIndexer
from orchestrators.indexing import strategies


_STRATEGIES: dict[RAGStrategy, type[AbstractIndexer]] = {
    RAGStrategy.NAIVE: strategies.NaiveIndexer,
}


def build_indexer(strategy: RAGStrategy) -> AbstractIndexer:
    """Build the indexer registered for `strategy`.

    Args:
        strategy: RAG strategy to build an indexer for.

    Returns:
        An indexer instance for `strategy`.

    Raises:
        UnsupportedError: If no indexer is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("index strategy", strategy)
    return _STRATEGIES[strategy]()
