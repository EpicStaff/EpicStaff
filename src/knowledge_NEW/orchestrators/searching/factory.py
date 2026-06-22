"""Factory for building searchers from a RAG strategy."""

from enums import RAGStrategy
from errors import UnsupportedError
from orchestrators.searching.base import AbstractSearch
from orchestrators.searching import strategies

_STRATEGIES: dict[RAGStrategy, type[AbstractSearch]] = {
    RAGStrategy.NAIVE: strategies.NaiveSearch,
}


def build_search(strategy: RAGStrategy) -> AbstractSearch:
    """Build the searcher registered for `strategy`.

    Args:
        strategy: RAG strategy to build a searcher for.

    Returns:
        A searcher instance for `strategy`.

    Raises:
        UnsupportedError: If no searcher is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("search strategy", strategy)
    return _STRATEGIES[strategy]()
