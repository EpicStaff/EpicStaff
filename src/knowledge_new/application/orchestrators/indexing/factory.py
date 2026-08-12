from application.orchestrators.indexing import strategies
from application.orchestrators.indexing.base import AbstractIndexer
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractIndexer]] = {
    RAGStrategy.NAIVE: strategies.NaiveIndexer,
    RAGStrategy.GRAPH: strategies.GraphIndexer,
}


def build_indexer(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractIndexer:
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
