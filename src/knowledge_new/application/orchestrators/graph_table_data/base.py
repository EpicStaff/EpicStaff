import abc

from application.commands import GetGraphTableData
from application.orchestrators.base import AbstractOrchestrator
from application.results import GraphTableDataResult


class AbstractGraphTableDataOrchestrator(
    AbstractOrchestrator[GetGraphTableData, GraphTableDataResult], abc.ABC
):
    """Read a single parquet table from the graph index and return paginated rows."""
