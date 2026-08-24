from application.orchestrators.searching import strategies
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractSearchOrchestrator]] = {
    RAGStrategy.NAIVE: strategies.NaiveSearchOrchestrator,
    RAGStrategy.GRAPH: strategies.GraphSearchOrchestrator,
}


def build_search(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractSearchOrchestrator:
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
