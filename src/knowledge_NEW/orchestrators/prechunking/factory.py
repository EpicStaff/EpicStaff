"""Factory for building prechunkers from a RAG strategy."""

from enums import RAGStrategy
from errors import UnsupportedError
from orchestrators.prechunking import strategies
from orchestrators.prechunking.base import AbstractPrechunker


_STRATEGIES: dict[RAGStrategy, type[AbstractPrechunker]] = {
    RAGStrategy.NAIVE: strategies.NaivePrechunker,
}


def build_prechunker(strategy: RAGStrategy) -> AbstractPrechunker:
    """Build the prechunker registered for `strategy`.

    Args:
        strategy: RAG strategy to build a prechunker for.

    Returns:
        A prechunker instance for `strategy`.

    Raises:
        UnsupportedError: If no prechunker is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("index strategy", strategy)
    return _STRATEGIES[strategy]()
