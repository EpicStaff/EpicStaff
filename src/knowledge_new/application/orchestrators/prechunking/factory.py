from application.orchestrators.prechunking import strategies
from application.orchestrators.prechunking.base import AbstractPrechunker
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractPrechunker]] = {
    RAGStrategy.NAIVE: strategies.NaivePrechunker,
}


def build_prechunker(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractPrechunker:
    """Build the prechunker registered for `strategy`.

    Args:
        strategy: RAG strategy to build a prechunker for.
        uow: Unit of work providing repository access.

    Raises:
        UnsupportedError: If no prechunker is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("index strategy", strategy)
    return _STRATEGIES[strategy](uow)
