from typing import TYPE_CHECKING

from application.orchestrators.graph_visualization.base import (
    AbstractEntityDetailOrchestrator,
    AbstractGraphVisualizationOrchestrator,
    AbstractRelationshipDetailOrchestrator,
)
from application.ports import AbstractUnitOfWork
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

if TYPE_CHECKING:
    from application.orchestrators.graph_visualization.strategies.graph import (
        EntityDetailOrchestrator,
        GraphVisualizationOrchestrator,
        RelationshipDetailOrchestrator,
    )
else:
    GraphVisualizationOrchestrator = LazyImport(
        "application.orchestrators.graph_visualization.strategies.graph",
        obj="GraphVisualizationOrchestrator",
    )
    EntityDetailOrchestrator = LazyImport(
        "application.orchestrators.graph_visualization.strategies.graph",
        obj="EntityDetailOrchestrator",
    )
    RelationshipDetailOrchestrator = LazyImport(
        "application.orchestrators.graph_visualization.strategies.graph",
        obj="RelationshipDetailOrchestrator",
    )

_VISUALIZATION_STRATEGIES: dict[RAGStrategy, type[AbstractGraphVisualizationOrchestrator]] = {
    RAGStrategy.GRAPH: GraphVisualizationOrchestrator
}

_ENTITY_DETAIL_STRATEGIES: dict[RAGStrategy, type[AbstractEntityDetailOrchestrator]] = {
    RAGStrategy.GRAPH: EntityDetailOrchestrator
}

_RELATIONSHIP_DETAIL_STRATEGIES: dict[RAGStrategy, type[AbstractRelationshipDetailOrchestrator]] = {
    RAGStrategy.GRAPH: RelationshipDetailOrchestrator
}


def build_graph_visualization(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractGraphVisualizationOrchestrator:
    """Build the graph visualization orchestrator registered for `strategy`.

    Only GRAPH is supported; NAIVE indexes have no graph structure to visualize.

    Raises:
        UnsupportedError: If no visualization orchestrator is registered for `strategy`.
    """
    if strategy not in _VISUALIZATION_STRATEGIES:
        raise UnsupportedError("visualization strategy", strategy)
    return _VISUALIZATION_STRATEGIES[strategy](uow)


def build_entity_detail(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractEntityDetailOrchestrator:
    """Build the entity detail orchestrator registered for `strategy`.

    Raises:
        UnsupportedError: If no entity detail orchestrator is registered for `strategy`.
    """
    if strategy not in _ENTITY_DETAIL_STRATEGIES:
        raise UnsupportedError("entity detail strategy", strategy)
    return _ENTITY_DETAIL_STRATEGIES[strategy](uow)


def build_relationship_detail(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractRelationshipDetailOrchestrator:
    """Build the relationship detail orchestrator registered for `strategy`.

    Raises:
        UnsupportedError: If no relationship detail orchestrator is registered for `strategy`.
    """
    if strategy not in _RELATIONSHIP_DETAIL_STRATEGIES:
        raise UnsupportedError("relationship detail strategy", strategy)
    return _RELATIONSHIP_DETAIL_STRATEGIES[strategy](uow)
