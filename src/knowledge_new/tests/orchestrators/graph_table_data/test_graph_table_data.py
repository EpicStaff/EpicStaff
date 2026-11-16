"""Tests for GraphTableDataOrchestrator and GraphTableSummaryOrchestrator.

Seam: FakeUoW / FakeGraphRagRepo for the database. The index tables are real parquet
files in a temporary directory, read through graphrag's file storage.
"""

import pandas
import pyarrow.lib
import pytest
from application.commands import GetGraphTableData, GetGraphTableSummary
from application.orchestrators.graph_table_data import (
    build_graph_table_data,
    build_graph_table_summary,
)
from application.orchestrators.graph_table_data.strategies.graph_table import (
    GraphTableDataOrchestrator,
)
from application.orchestrators.graph_table_data.strategies.graph_table_summary import (
    GraphTableSummaryOrchestrator,
)
from domain.enums import RAGStrategy
from domain.errors import GraphNotIndexedError, GraphRagConfigNotFoundError, UnsupportedError

from tests.orchestrators.graph_output_fakes import FakeGraphRagRepo, FakeUoW, write_table

ENTITY_COLUMNS = ["id", "title", "type", "description", "degree"]


@pytest.fixture
def uow(tmp_path) -> FakeUoW:
    return FakeUoW(FakeGraphRagRepo(tmp_path))


def _entities(count: int) -> pandas.DataFrame:
    return pandas.DataFrame(
        {
            "id": [f"e{index}" for index in range(count)],
            "title": [f"Entity{index}" for index in range(count)],
            "type": ["ORG"] * count,
            "description": [f"description {index}" for index in range(count)],
            "degree": list(range(count)),
            # A column the endpoint does not show: it must not reach the rows.
            "text_unit_ids": [["t0"] for _ in range(count)],
        }
    )


async def _table_data(uow, table_name: str = "entities", **command_fields):
    command = GetGraphTableData(rag_id=42, table_name=table_name, **command_fields)
    return await GraphTableDataOrchestrator(uow).execute(command)


# -- Paging --


async def test_first_page_returns_fixed_columns_and_total(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(25))

    result = await _table_data(uow, page=1, page_size=10)

    assert result.columns == ENTITY_COLUMNS
    assert [row["id"] for row in result.rows] == [f"e{index}" for index in range(10)]
    assert set(result.rows[0]) == set(ENTITY_COLUMNS)
    assert result.rows[0]["degree"] == 0
    assert type(result.rows[0]["degree"]) is int
    assert result.total == 25
    assert (result.page, result.page_size) == (1, 10)


async def test_last_partial_page_returns_the_remaining_rows(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(25))

    result = await _table_data(uow, page=3, page_size=10)

    assert [row["id"] for row in result.rows] == ["e20", "e21", "e22", "e23", "e24"]
    assert result.total == 25


async def test_page_past_the_end_is_empty_but_keeps_the_total(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(25))

    result = await _table_data(uow, page=4, page_size=10)

    assert result.rows == []
    assert result.total == 25


async def test_page_size_equal_to_row_count_returns_everything_on_one_page(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(100))

    first_page = await _table_data(uow, page=1, page_size=100)
    second_page = await _table_data(uow, page=2, page_size=100)

    assert len(first_page.rows) == 100
    assert second_page.rows == []


async def test_page_size_of_one_returns_a_single_row(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(5))

    result = await _table_data(uow, page=5, page_size=1)

    assert [row["id"] for row in result.rows] == ["e4"]


# -- Search --


@pytest.mark.parametrize("search", ["C++", "(", "[a-z]", ".*", "\\"])
async def test_search_matches_regex_characters_literally(tmp_path, uow, search):
    entities = _entities(3)
    entities.loc[1, "description"] = f"written in {search} mostly"
    write_table(tmp_path, "entities", entities)

    result = await _table_data(uow, search=search)

    assert [row["id"] for row in result.rows] == ["e1"]
    assert result.total == 1


async def test_search_is_case_insensitive_across_all_shown_columns(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))

    by_title = await _table_data(uow, search="entity2")
    by_description = await _table_data(uow, search="DESCRIPTION 0")

    assert [row["id"] for row in by_title.rows] == ["e2"]
    assert [row["id"] for row in by_description.rows] == ["e0"]


async def test_search_does_not_match_missing_values(tmp_path, uow):
    entities = _entities(3)
    entities["type"] = [None, None, None]
    entities["description"] = [None, "nanotech", None]
    write_table(tmp_path, "entities", entities)

    nan_matches = await _table_data(uow, search="nan")
    none_matches = await _table_data(uow, search="none")

    assert [row["id"] for row in nan_matches.rows] == ["e1"]
    assert none_matches.rows == []
    assert nan_matches.rows[0]["type"] is None


async def test_search_does_not_match_columns_that_are_not_shown(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))

    result = await _table_data(uow, search="t0")

    assert result.rows == []


async def test_search_total_counts_matches_and_pages_over_them(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(30))

    # "Entity1" matches Entity1 and Entity10..Entity19.
    result = await _table_data(uow, search="Entity1", page=2, page_size=5)

    assert result.total == 11
    assert [row["id"] for row in result.rows] == ["e14", "e15", "e16", "e17", "e18"]


# -- Missing data, unknown table, unknown RAG --


async def test_optional_table_missing_from_an_indexed_graph_returns_empty_result(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))

    result = await _table_data(uow, table_name="covariates", page=1, page_size=10)

    assert result.rows == []
    assert result.total == 0
    assert result.columns == [
        "id",
        "subject_id",
        "subject_type",
        "covariate_type",
        "description",
    ]


@pytest.mark.parametrize("table_name", ["entities", "covariates"])
async def test_table_of_a_never_indexed_graph_raises_graph_not_indexed(uow, table_name):
    with pytest.raises(GraphNotIndexedError):
        await _table_data(uow, table_name=table_name)


async def test_table_written_before_graph_extraction_is_readable_without_entities(tmp_path, uow):
    write_table(tmp_path, "documents", pandas.DataFrame({"id": ["d0"], "title": ["Report"]}))

    result = await _table_data(uow, table_name="documents")

    assert [row["id"] for row in result.rows] == ["d0"]


async def test_columns_missing_from_the_file_are_returned_empty(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(2).drop(columns=["type"]))

    result = await _table_data(uow)

    assert [row["type"] for row in result.rows] == [None, None]


async def test_unknown_table_raises_unsupported(uow):
    with pytest.raises(UnsupportedError):
        await GraphTableDataOrchestrator(uow).execute(
            GetGraphTableData(rag_id=42, table_name="secrets")
        )


async def test_table_data_for_unknown_rag_raises_config_not_found():
    uow = FakeUoW(FakeGraphRagRepo(output_directory=None))

    with pytest.raises(GraphRagConfigNotFoundError):
        await GraphTableDataOrchestrator(uow).execute(
            GetGraphTableData(rag_id=42, table_name="entities")
        )


def test_table_data_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_graph_table_data(RAGStrategy.NAIVE, uow)


# -- Summary --


async def test_summary_counts_rows_of_each_table_and_zero_for_missing_ones(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(7))
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame({"id": ["r0", "r1"], "source": ["a", "b"], "target": ["b", "c"]}),
    )

    result = await GraphTableSummaryOrchestrator(uow).execute(GetGraphTableSummary(rag_id=42))

    counts = {item.name: item.count for item in result.tables}
    assert counts == {
        "communities": 0,
        "community_reports": 0,
        "covariates": 0,
        "documents": 0,
        "entities": 7,
        "relationships": 2,
        "text_units": 0,
    }
    labels = {item.name: item.label for item in result.tables}
    assert labels["community_reports"] == "Community Reports"
    assert [item.name for item in result.tables] == sorted(counts)


async def test_summary_of_a_never_indexed_graph_raises_graph_not_indexed(uow):
    with pytest.raises(GraphNotIndexedError):
        await GraphTableSummaryOrchestrator(uow).execute(GetGraphTableSummary(rag_id=42))


async def test_summary_raises_on_a_corrupt_table_instead_of_counting_zero(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))
    (tmp_path / "relationships.parquet").write_bytes(b"not a parquet file")

    # The counts run in a TaskGroup, so the decoding error arrives grouped.
    with pytest.raises(ExceptionGroup) as raised:
        await GraphTableSummaryOrchestrator(uow).execute(GetGraphTableSummary(rag_id=42))

    assert raised.group_contains(pyarrow.lib.ArrowInvalid)


async def test_summary_for_unknown_rag_raises_config_not_found():
    uow = FakeUoW(FakeGraphRagRepo(output_directory=None))

    with pytest.raises(GraphRagConfigNotFoundError):
        await GraphTableSummaryOrchestrator(uow).execute(GetGraphTableSummary(rag_id=42))


def test_summary_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_graph_table_summary(RAGStrategy.NAIVE, uow)
