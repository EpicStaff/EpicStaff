from application.orchestrators.metrics import strategies
from application.orchestrators.metrics.base import AbstractMetricsOrchestrator
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractMetricsOrchestrator]] = {
    RAGStrategy.GRAPH: strategies.GraphMetricsOrchestrator,
}


def build_metrics(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractMetricsOrchestrator:
    """Build the metrics orchestrator registered for `strategy`.

    Naive metrics are served from the Django DB, so only GRAPH is registered.

    Raises:
        UnsupportedError: If no metrics orchestrator is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("metrics strategy", strategy)
    return _STRATEGIES[strategy](uow)
