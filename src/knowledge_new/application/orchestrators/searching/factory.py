from typing import TYPE_CHECKING

from application.orchestrators.searching import strategies
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.ports import AbstractUnitOfWork
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError
from foundation.cryptographer import AbstractCryptographer

if TYPE_CHECKING:
    from application.orchestrators.searching.strategies.graph_search import (
        GraphSearchOrchestrator,
    )
else:
    GraphSearchOrchestrator = LazyImport(
        "application.orchestrators.searching.strategies.graph_search",
        obj="GraphSearchOrchestrator",
    )

_STRATEGIES: dict[RAGStrategy, type[AbstractSearchOrchestrator]] = {
    RAGStrategy.NAIVE: strategies.NaiveSearchOrchestrator,
    RAGStrategy.GRAPH: GraphSearchOrchestrator,
}


def build_search(
    strategy: RAGStrategy, uow: AbstractUnitOfWork, cryptographer: AbstractCryptographer
) -> AbstractSearchOrchestrator:
    """Build the searcher registered for `strategy`.

    Args:
        strategy: RAG strategy to build a searcher for.
        uow: Unit of work providing repository access.
        cryptographer: Opens the secrets sealed in the command.

    Raises:
        UnsupportedError: If no searcher is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("search strategy", strategy)
    return _STRATEGIES[strategy](uow, cryptographer)
