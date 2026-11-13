from typing import TYPE_CHECKING

from application.orchestrators.graph_table_data.base import AbstractGraphTableDataOrchestrator
from application.ports import AbstractUnitOfWork
from common.lazy_import import LazyImport
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

if TYPE_CHECKING:
    from application.orchestrators.graph_table_data.strategies.graph_table import (
        GraphTableDataOrchestrator,
    )
    from application.orchestrators.graph_table_data.strategies.graph_table_summary import (
        GraphTableSummaryOrchestrator,
    )
else:
    GraphTableDataOrchestrator = LazyImport(
        "application.orchestrators.graph_table_data.strategies.graph_table",
        obj="GraphTableDataOrchestrator",
    )
    GraphTableSummaryOrchestrator = LazyImport(
        "application.orchestrators.graph_table_data.strategies.graph_table_summary",
        obj="GraphTableSummaryOrchestrator",
    )

_STRATEGIES: dict[RAGStrategy, type[AbstractGraphTableDataOrchestrator]] = {
    RAGStrategy.GRAPH: GraphTableDataOrchestrator
}

_SUMMARY_STRATEGIES: dict[RAGStrategy, type] = {
    RAGStrategy.GRAPH: GraphTableSummaryOrchestrator
}


def build_graph_table_data(
    strategy: RAGStrategy, uow: AbstractUnitOfWork
) -> AbstractGraphTableDataOrchestrator:
    """Build the graph table-data orchestrator registered for `strategy`.

    Only GRAPH is supported; NAIVE indexes have no graph tables to browse.

    Raises:
        UnsupportedError: If no table-data orchestrator is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError("table data strategy", strategy)
    return _STRATEGIES[strategy](uow)


def build_graph_table_summary(strategy: RAGStrategy, uow: AbstractUnitOfWork):
    """Build the graph table-summary orchestrator registered for `strategy`.

    Only GRAPH is supported; NAIVE indexes have no graph tables to browse.

    Raises:
        UnsupportedError: If no table-summary orchestrator is registered for `strategy`.
    """
    if strategy not in _SUMMARY_STRATEGIES:
        raise UnsupportedError("table summary strategy", strategy)
    return _SUMMARY_STRATEGIES[strategy](uow)
