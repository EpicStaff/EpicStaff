from application.orchestrators.removing import strategies
from application.orchestrators.removing.base import AbstractRagRemoveOrchestrator
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractRagRemoveOrchestrator]] = {
    RAGStrategy.GRAPH: strategies.GraphRagRemoveOrchestrator,
}


def build_remover(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractRagRemoveOrchestrator:
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
