import asyncio

import numpy
import pandas
from application.commands import GetGraphTableData
from application.orchestrators.graph_output import (
    ensure_graph_indexed,
    open_graph_output_storage,
    read_output_table,
)
from application.orchestrators.graph_table_data.base import AbstractGraphTableDataOrchestrator
from application.results import GraphTableDataResult
from domain.enums import GraphOutputTableEnum
from domain.errors import UnsupportedError

# Fixed column sets per table — only user-facing columns, not every parquet column.
_TABLE_COLUMNS: dict[GraphOutputTableEnum, list[str]] = {
    GraphOutputTableEnum.ENTITIES: ["id", "title", "type", "description", "degree"],
    GraphOutputTableEnum.RELATIONSHIPS: ["id", "source", "target", "description", "weight"],
    GraphOutputTableEnum.COMMUNITIES: ["id", "title", "level", "size"],
    GraphOutputTableEnum.DOCUMENTS: ["id", "human_readable_id", "title"],
    GraphOutputTableEnum.TEXT_UNITS: ["id", "text", "n_tokens"],
    GraphOutputTableEnum.COMMUNITY_REPORTS: ["id", "title", "summary"],
    GraphOutputTableEnum.COVARIATES: [
        "id",
        "subject_id",
        "subject_type",
        "covariate_type",
        "description",
    ],
}

SUPPORTED_TABLES: frozenset[str] = frozenset(table.value for table in _TABLE_COLUMNS)


def _sanitize_value(value: object) -> object:
    """Convert numpy/pandas values to plain Python for JSON serialization."""
    if value is None or value is pandas.NA or value is pandas.NaT:
        return None
    if isinstance(value, (float, numpy.floating)) and numpy.isnan(value):
        return None
    if isinstance(value, numpy.integer):
        return int(value)
    if isinstance(value, numpy.floating):
        return float(value)
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    return value


def _rows_containing(dataframe: pandas.DataFrame, search: str) -> pandas.DataFrame:
    """Keep the rows where any cell contains `search` as plain text, ignoring case.

    A missing cell never matches, so a search for "nan" or "none" finds only real text.
    """
    mask = pandas.Series(False, index=dataframe.index)
    for column in dataframe.columns:
        values = dataframe[column]
        mask |= values.notna() & values.astype(str).str.contains(
            search, case=False, regex=False, na=False
        )
    return dataframe.loc[mask]


def _select_page(
    dataframe: pandas.DataFrame,
    columns: list[str],
    search: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, object]], int]:
    """Filter, then cut out one page. Returns the page's rows and the filtered total."""
    # Missing columns become empty, so every row carries the full fixed column set.
    dataframe = dataframe.reindex(columns=columns)
    if search:
        dataframe = _rows_containing(dataframe, search)

    start = (page - 1) * page_size
    page_records = dataframe.iloc[start : start + page_size].to_dict("records")
    rows = [
        {column: _sanitize_value(value) for column, value in record.items()}
        for record in page_records
    ]
    return rows, len(dataframe)


class GraphTableDataOrchestrator(AbstractGraphTableDataOrchestrator):
    async def on_execute(self, command: GetGraphTableData) -> GraphTableDataResult:
        if command.table_name not in SUPPORTED_TABLES:
            raise UnsupportedError(that="table name", got=command.table_name)

        columns = _TABLE_COLUMNS[command.table_name]
        storage = await open_graph_output_storage(self.uow, command.rag_id)
        dataframe = await read_output_table(storage, command.table_name, columns)

        rows: list[dict[str, object]] = []
        total = 0
        if dataframe is None:
            # An optional table an indexed graph did not produce is simply empty.
            await ensure_graph_indexed(storage, command.rag_id)
        else:
            rows, total = await asyncio.to_thread(
                _select_page,
                dataframe,
                columns,
                command.search,
                command.page,
                command.page_size,
            )

        return GraphTableDataResult(
            columns=columns,
            rows=rows,
            total=total,
            page=command.page,
            page_size=command.page_size,
        )
