from enums import RAGStrategy
from errors import UnsupportedError
from orchestrators.searching.base import AbstractSearch
from orchestrators.searching import strategies
from database.unit_of_work import AbstractUnitOfWork

_STRATEGIES: dict[RAGStrategy, type[AbstractSearch]] = {
    RAGStrategy.NAIVE: strategies.NaiveSearch,
}


def build_search(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractSearch:
    """Build the searcher registered for `strategy`.

    Args:
        strategy: RAG strategy to build a searcher for.
        uow: Unit of work providing repository access.

    Raises:
        UnsupportedError: If no searcher is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("search strategy", strategy)
    return _STRATEGIES[strategy](uow)
