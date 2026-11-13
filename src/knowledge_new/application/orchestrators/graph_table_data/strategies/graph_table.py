import numpy
import pandas
from application.commands import GetGraphTableData
from application.orchestrators.graph_table_data.base import AbstractGraphTableDataOrchestrator
from application.results import GraphTableDataResult
from domain.errors import UnsupportedError
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider

# Fixed column sets per table — only user-facing columns, not every parquet column.
_TABLE_COLUMNS: dict[str, list[str]] = {
    "entities": ["id", "title", "type", "description", "degree"],
    "relationships": ["id", "source", "target", "description", "weight"],
    "communities": ["id", "title", "level", "size"],
    "documents": ["id", "human_readable_id", "title"],
    "text_units": ["id", "text", "n_tokens"],
    "community_reports": ["id", "title", "summary"],
    "covariates": ["id", "subject_id", "subject_type", "covariate_type", "description"],
}

SUPPORTED_TABLES: frozenset[str] = frozenset(_TABLE_COLUMNS)


def _sanitize_value(value: object) -> object:
    """Convert numpy/pandas types to plain Python for JSON serialization."""
    if value is None:
        return None
    if isinstance(value, (float, numpy.floating)) and pandas.isna(value):
        return None
    if isinstance(value, numpy.integer):
        return int(value)
    if isinstance(value, numpy.floating):
        return float(value)
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    return value


class GraphTableDataOrchestrator(AbstractGraphTableDataOrchestrator):
    async def on_execute(self, command: GetGraphTableData) -> GraphTableDataResult:
        if command.table_name not in SUPPORTED_TABLES:
            raise UnsupportedError(that="table name", got=command.table_name)

        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)

        columns = _TABLE_COLUMNS[command.table_name]

        try:
            reader_method = getattr(reader, command.table_name)
            dataframe: pandas.DataFrame = await reader_method()
        except (ValueError, FileNotFoundError):
            return GraphTableDataResult(
                columns=columns,
                rows=[],
                total=0,
                page=command.page,
                page_size=command.page_size,
            )

        # Keep only the fixed columns; missing ones become NaN.
        dataframe = dataframe.reindex(columns=columns)

        if command.search:
            mask = pandas.Series(False, index=dataframe.index)
            for column in columns:
                mask = mask | (
                    dataframe[column]
                    .astype(str)
                    .str.contains(command.search, case=False, na=False)
                )
            dataframe = dataframe.loc[mask]

        total = len(dataframe)

        start = (command.page - 1) * command.page_size
        end = start + command.page_size
        page_df = dataframe.iloc[start:end]

        rows = [
            {column: _sanitize_value(row[column]) for column in columns}
            for _, row in page_df.iterrows()
        ]

        return GraphTableDataResult(
            columns=columns,
            rows=rows,
            total=total,
            page=command.page,
            page_size=command.page_size,
        )
