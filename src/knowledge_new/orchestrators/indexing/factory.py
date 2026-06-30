from database.unit_of_work import AbstractUnitOfWork
from enums import RAGStrategy
from errors import UnsupportedError
from orchestrators.indexing import strategies
from orchestrators.indexing.base import AbstractIndexer

_STRATEGIES: dict[RAGStrategy, type[AbstractIndexer]] = {
    RAGStrategy.NAIVE: strategies.NaiveIndexer,
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
