from typing import TYPE_CHECKING

from application.orchestrators.removing.base import AbstractRagRemoveOrchestrator
from application.ports import AbstractUnitOfWork
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

if TYPE_CHECKING:
    from application.orchestrators.removing.strategies.graph_remover import (
        GraphRagRemoveOrchestrator,
    )
else:
    GraphRagRemoveOrchestrator = LazyImport(
        "application.orchestrators.removing.strategies.graph_remover",
        obj="GraphRagRemoveOrchestrator",
    )

_STRATEGIES: dict[RAGStrategy, type[AbstractRagRemoveOrchestrator]] = {
    RAGStrategy.GRAPH: GraphRagRemoveOrchestrator,
}


def build_remover(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractRagRemoveOrchestrator:
    """Build the remover registered for `strategy`.

    Args:
        strategy: RAG strategy to build a remover for.
        uow: Unit of work providing repository access.

    Raises:
        UnsupportedError: If no remover is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("remove strategy", strategy)
    return _STRATEGIES[strategy](uow)
