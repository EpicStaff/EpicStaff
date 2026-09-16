from application.orchestrators.indexing import strategies
from application.orchestrators.indexing.base import AbstractIndexOrchestrator
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractIndexOrchestrator]] = {
    RAGStrategy.NAIVE: strategies.NaiveIndexOrchestrator,
    RAGStrategy.GRAPH: strategies.GraphIndexOrchestrator,
}


def build_indexer(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractIndexOrchestrator:
    """Build the indexer registered for `strategy`.

    Args:
        strategy: RAG strategy to build an indexer for.
        uow: Unit of work providing repository access.

    Raises:
        UnsupportedError: If no indexer is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("index strategy", strategy)
    return _STRATEGIES[strategy](uow)
