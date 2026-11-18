import asyncio

from application.commands import GetGraphTableSummary
from application.orchestrators.base import AbstractOrchestrator
from application.orchestrators.graph_output import (
    count_output_table_rows,
    ensure_graph_indexed,
    open_graph_output_storage,
)
from application.orchestrators.graph_table_data.strategies.graph_table import (
    SUPPORTED_TABLES,
)
from application.results import GraphTableSummaryItem, GraphTableSummaryResult


def _make_label(name: str) -> str:
    """Convert a snake_case table name to a human-readable title.

    "entities" -> "Entities", "text_units" -> "Text Units",
    "community_reports" -> "Community Reports".
    """
    return name.replace("_", " ").title()


class GraphTableSummaryOrchestrator(
    AbstractOrchestrator[GetGraphTableSummary, GraphTableSummaryResult]
):
    async def on_execute(self, command: GetGraphTableSummary) -> GraphTableSummaryResult:
        storage = await open_graph_output_storage(self.uow, command.rag_id)
        await ensure_graph_indexed(storage, command.rag_id)

        table_names = sorted(SUPPORTED_TABLES)
        # A TaskGroup cancels the remaining downloads as soon as one table fails to read.
        async with asyncio.TaskGroup() as task_group:
            count_tasks = [
                task_group.create_task(count_output_table_rows(storage, table_name))
                for table_name in table_names
            ]

        # A table the index has not written (covariates are optional) counts as empty;
        # a file that exists but cannot be read fails the request instead.
        return GraphTableSummaryResult(
            tables=[
                GraphTableSummaryItem(
                    name=table_name,
                    label=_make_label(table_name),
                    count=count_task.result() or 0,
                )
                for table_name, count_task in zip(table_names, count_tasks, strict=True)
            ]
        )
