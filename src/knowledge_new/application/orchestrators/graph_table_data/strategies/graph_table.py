import asyncio
from collections.abc import Iterable

import numpy
import pandas
from application.commands import GetGraphTableData
from application.orchestrators.graph_output import (
    ensure_graph_indexed,
    open_graph_output_storage,
    read_output_table,
)
from application.orchestrators.graph_table_data.base import AbstractGraphTableDataOrchestrator
from application.orchestrators.graph_table_data.link_resolver import (
    LINK_COLUMNS,
    LinkTableReader,
    resolve_link_mask,
)
from application.results import GraphTableDataResult
from domain.enums import GraphOutputTableEnum, GraphTableSearchScope
from domain.errors import UnsupportedError
from graphrag_storage import Storage

# Fixed column sets per table — only user-facing columns, not every parquet column.
_TABLE_COLUMNS: dict[GraphOutputTableEnum, list[str]] = {
    GraphOutputTableEnum.ENTITIES: ["id", "title", "type", "description", "degree"],
    GraphOutputTableEnum.RELATIONSHIPS: ["id", "source", "target", "description", "weight"],
    GraphOutputTableEnum.COMMUNITIES: ["id", "community", "title", "level", "size"],
    GraphOutputTableEnum.DOCUMENTS: ["id", "human_readable_id", "title"],
    GraphOutputTableEnum.TEXT_UNITS: ["id", "text", "n_tokens"],
    GraphOutputTableEnum.COMMUNITY_REPORTS: ["id", "community", "title", "summary"],
    GraphOutputTableEnum.COVARIATES: [
        "id",
        "subject_id",
        "subject_type",
        "covariate_type",
        "description",
    ],
}

SUPPORTED_TABLES: frozenset[str] = frozenset(table.value for table in _TABLE_COLUMNS)

# Columns the `identity` search scope matches against. These are the fields the linked-to
# picker uses to label a row (see `pickLinkedToRowLabel` in the frontend) plus the row id.
# Tables without a title fall back to the content field the picker already displays
# (text_units.text, covariates.subject_id), so the search surface matches the visible label.
_IDENTITY_SEARCH_COLUMNS: dict[GraphOutputTableEnum, list[str]] = {
    GraphOutputTableEnum.ENTITIES: ["id", "title"],
    GraphOutputTableEnum.RELATIONSHIPS: ["id", "source", "target"],
    GraphOutputTableEnum.COMMUNITIES: ["id", "title"],
    GraphOutputTableEnum.COMMUNITY_REPORTS: ["id", "title"],
    GraphOutputTableEnum.TEXT_UNITS: ["id", "text"],
    GraphOutputTableEnum.DOCUMENTS: ["id", "title"],
    GraphOutputTableEnum.COVARIATES: ["id", "subject_id"],
}


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


def _rows_containing(
    dataframe: pandas.DataFrame, search: str, columns: Iterable[str] | None = None
) -> pandas.DataFrame:
    """Keep rows where any of `columns` contains `search` as plain text, ignoring case.

    A missing cell never matches, so a search for "nan" or "none" finds only real text.
    A column requested but absent from `dataframe` is skipped; the default `None` scans
    every column — the main-table behaviour.
    """
    mask = pandas.Series(False, index=dataframe.index)
    scanned = [column for column in (columns or dataframe.columns) if column in dataframe.columns]
    for column in scanned:
        values = dataframe[column]
        mask |= values.notna() & values.astype(str).str.contains(
            search, case=False, regex=False, na=False
        )
    return dataframe.loc[mask]


def _rows_equal(dataframe: pandas.DataFrame, column: str, value: str) -> pandas.DataFrame:
    """Keep rows where `column` equals `value` as text. Missing cells never match."""
    values = dataframe[column]
    present = values.notna()
    if pandas.api.types.is_numeric_dtype(values):
        try:
            numeric_value = float(value)
        except ValueError:
            # A non-numeric filter value on a numeric column matches nothing.
            return dataframe.iloc[0:0]
        mask = present & (values == numeric_value)
    else:
        mask = present & (values.astype(str) == value)
    return dataframe.loc[mask]


def _select_page(
    dataframe: pandas.DataFrame,
    columns: list[str],
    search: str | None,
    page: int,
    page_size: int,
    filter_column: str | None = None,
    filter_value: str | None = None,
    search_columns: Iterable[str] | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Filter, then cut out one page. Returns the page's rows and the filtered total."""
    # Missing columns become empty, so every row carries the full fixed column set.
    dataframe = dataframe.reindex(columns=columns)
    if filter_column is not None and filter_value is not None:
        dataframe = _rows_equal(dataframe, filter_column, filter_value)
    if search:
        dataframe = _rows_containing(dataframe, search, search_columns)

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

        subject_type = GraphOutputTableEnum(command.table_name)
        columns = _TABLE_COLUMNS[subject_type]
        if (command.filter_column is None) != (command.filter_value is None):
            raise UnsupportedError(
                that="filter pair", got="filter_column and filter_value must be set together"
            )
        if command.filter_column is not None and command.filter_column not in columns:
            raise UnsupportedError(that="filter column", got=command.filter_column)
        storage = await open_graph_output_storage(self.uow, command.rag_id)

        rows, total = await self._read_page(storage, subject_type, columns, command)

        return GraphTableDataResult(
            columns=columns,
            rows=rows,
            total=total,
            page=command.page,
            page_size=command.page_size,
        )

    async def _read_page(
        self,
        storage: Storage,
        subject_type: GraphOutputTableEnum,
        columns: list[str],
        command: GetGraphTableData,
    ) -> tuple[list[dict[str, object]], int]:
        read_columns = columns
        reader: LinkTableReader | None = None
        if command.linked_to_type is not None:
            reader = LinkTableReader(storage)
            # Preload the subject with its link columns so the resolver can join without
            # a second read; the extras are dropped before the rows reach the response.
            read_columns = _merge_columns(columns, LINK_COLUMNS[subject_type])
        dataframe = await read_output_table(storage, subject_type, read_columns)
        if dataframe is None:
            # An optional table an indexed graph did not produce is simply empty.
            await ensure_graph_indexed(storage, command.rag_id)
            return [], 0

        if reader is not None:
            # Cache the subject under its own type: other resolver steps may read it too
            # (e.g. communities → community_reports starts from the reports table).
            reader.seed(subject_type, dataframe)
            mask = await resolve_link_mask(
                dataframe,
                subject_type,
                command.linked_to_type,
                command.linked_to_id,
                reader,
            )
            dataframe = dataframe.loc[mask]

        search_columns = (
            _IDENTITY_SEARCH_COLUMNS[subject_type]
            if command.search_scope is GraphTableSearchScope.IDENTITY
            else None
        )
        return await asyncio.to_thread(
            _select_page,
            dataframe,
            columns,
            command.search,
            command.page,
            command.page_size,
            command.filter_column,
            command.filter_value,
            search_columns,
        )


def _merge_columns(primary: list[str], extra: list[str]) -> list[str]:
    """Return `primary` with every `extra` not already present appended in order."""
    seen = set(primary)
    merged = list(primary)
    for column in extra:
        if column not in seen:
            merged.append(column)
            seen.add(column)
    return merged
