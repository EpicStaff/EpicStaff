from typing import TYPE_CHECKING

from application.orchestrators.graph_visualization.base import AbstractGraphVisualizationOrchestrator
from application.ports import AbstractUnitOfWork
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

if TYPE_CHECKING:
    from application.orchestrators.graph_visualization.strategies.graph import (
        GraphVisualizationOrchestrator,
    )
else:
    GraphVisualizationOrchestrator = LazyImport(
        "application.orchestrators.graph_visualization.strategies.graph",
        obj="GraphVisualizationOrchestrator",
    )

_STRATEGIES: dict[RAGStrategy, type[AbstractGraphVisualizationOrchestrator]] = {
    RAGStrategy.GRAPH: GraphVisualizationOrchestrator
}


def build_graph_visualization(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractGraphVisualizationOrchestrator:
    """Build the graph visualization orchestrator registered for `strategy`.

    Only GRAPH is supported; NAIVE indexes have no graph structure to visualize.

    Raises:
        UnsupportedError: If no visualization orchestrator is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("visualization strategy", strategy)
    return _STRATEGIES[strategy](uow)
