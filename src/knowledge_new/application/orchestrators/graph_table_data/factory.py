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
else:
    GraphTableDataOrchestrator = LazyImport(
        "application.orchestrators.graph_table_data.strategies.graph_table",
        obj="GraphTableDataOrchestrator",
    )

_STRATEGIES: dict[RAGStrategy, type[AbstractGraphTableDataOrchestrator]] = {
    RAGStrategy.GRAPH: GraphTableDataOrchestrator
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
