import pandas
from application.commands import GetGraphTableSummary
from application.orchestrators.base import AbstractOrchestrator
from application.orchestrators.graph_table_data.strategies.graph_table import (
    SUPPORTED_TABLES,
)
from application.results import GraphTableSummaryItem, GraphTableSummaryResult
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider


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
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)

        items: list[GraphTableSummaryItem] = []
        for table_name in sorted(SUPPORTED_TABLES):
            try:
                reader_method = getattr(reader, table_name)
                dataframe: pandas.DataFrame = await reader_method()
                count = len(dataframe)
            except (ValueError, FileNotFoundError):
                count = 0

            items.append(
                GraphTableSummaryItem(
                    name=table_name,
                    label=_make_label(table_name),
                    count=count,
                )
            )

        return GraphTableSummaryResult(tables=items)
