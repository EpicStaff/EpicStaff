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
from application.orchestrators.graph_table_data.link_resolver import ALLOWED_PAIRS, _RESOLVERS
from application.orchestrators.graph_table_data.strategies.graph_table import (
    GraphTableDataOrchestrator,
)
from application.orchestrators.graph_table_data.strategies.graph_table_summary import (
    GraphTableSummaryOrchestrator,
)
from domain.enums import GraphOutputTableEnum, GraphTableSearchScope, RAGStrategy
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


# -- Exact-match column filter --


async def test_exact_filter_returns_only_rows_equal_to_value(tmp_path, uow):
    entities = _entities(5)
    entities["degree"] = [7, 17, 70, 7, 700]
    write_table(tmp_path, "entities", entities)

    result = await _table_data(uow, filter_column="degree", filter_value="7")

    assert [row["id"] for row in result.rows] == ["e0", "e3"]
    assert result.total == 2


async def test_exact_filter_and_search_intersect(tmp_path, uow):
    entities = _entities(5)
    entities["degree"] = [7, 7, 7, 7, 7]
    entities.loc[1, "description"] = "written in C++"
    entities.loc[3, "description"] = "written in python"
    write_table(tmp_path, "entities", entities)

    result = await _table_data(
        uow, filter_column="degree", filter_value="7", search="C++"
    )

    assert [row["id"] for row in result.rows] == ["e1"]
    assert result.total == 1


async def test_exact_filter_does_not_match_missing_cells(tmp_path, uow):
    entities = _entities(3)
    entities["description"] = [None, "something", None]
    write_table(tmp_path, "entities", entities)

    result = await _table_data(uow, filter_column="description", filter_value="nan")

    assert result.rows == []
    assert result.total == 0


async def test_exact_filter_column_not_in_table_raises_unsupported(uow):
    with pytest.raises(UnsupportedError):
        await _table_data(uow, filter_column="not_a_column", filter_value="x")


async def test_exact_filter_requires_both_column_and_value(uow):
    with pytest.raises(UnsupportedError):
        await _table_data(uow, filter_column="degree")
    with pytest.raises(UnsupportedError):
        await _table_data(uow, filter_value="7")


async def test_exact_filter_matches_integers_stored_as_float(tmp_path, uow):
    # A pandas column with any null promotes int64 → float64, so integer `1` lands as `1.0`.
    # The filter has to match "1" against that, not depend on `astype(str) == "1.0"`.
    entities = _entities(4)
    entities["degree"] = [1.0, 11.0, None, 1.0]
    write_table(tmp_path, "entities", entities)

    result = await _table_data(uow, filter_column="degree", filter_value="1")

    assert [row["id"] for row in result.rows] == ["e0", "e3"]
    assert result.total == 2


async def test_exact_filter_on_numeric_column_with_non_numeric_value_matches_nothing(
    tmp_path, uow
):
    write_table(tmp_path, "entities", _entities(3))

    result = await _table_data(uow, filter_column="degree", filter_value="not-a-number")

    assert result.rows == []
    assert result.total == 0


# -- Linked-to filter: shared fixtures --


def _write_two_documents_linked_to_two_communities(output_directory):
    # Document d0 owns text units t0, t1; d1 owns t2.
    write_table(
        output_directory,
        "documents",
        pandas.DataFrame(
            {
                "id": ["d0", "d1"],
                "human_readable_id": [1, 2],
                "title": ["Doc0", "Doc1"],
                "text_unit_ids": [["t0", "t1"], ["t2"]],
            }
        ),
    )
    # Community 10 spans t0 (→ d0); community 20 spans t2 (→ d1).
    write_table(
        output_directory,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c10", "c20"],
                "community": [10, 20],
                "parent": ["-1", "-1"],
                "children": [[], []],
                "title": ["Comm10", "Comm20"],
                "level": [0, 0],
                "size": [2, 1],
                "entity_ids": [["e0", "e1"], ["e2"]],
                "relationship_ids": [["r0"], []],
                "text_unit_ids": [["t0"], ["t2"]],
            }
        ),
    )
    # Two reports, one per community.
    write_table(
        output_directory,
        "community_reports",
        pandas.DataFrame(
            {
                "id": ["cr10", "cr20"],
                "community": [10, 20],
                "title": ["Report10", "Report20"],
                "summary": ["summary 10", "summary 20"],
            }
        ),
    )


# -- Linked-to filter: entities ↔ relationships (graph adjacency, not co-mention) --


async def test_entities_filtered_by_entities_uses_relationship_adjacency(tmp_path, uow):
    # Three entities share the same text unit (co-mention), but only two are graph
    # neighbours of Alpha via relationships. The old text_units backbone would have
    # surfaced all co-mentioned entities; the rewrite restricts to actual neighbours.
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": ["e0", "e1", "e2", "e3"],
                "title": ["Alpha", "Beta", "Gamma", "Delta"],
                "type": ["ORG"] * 4,
                "description": ["a", "b", "g", "d"],
                "degree": [0, 0, 0, 0],
                "text_unit_ids": [["t0"], ["t0"], ["t0"], ["t0"]],
            }
        ),
    )
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0", "r1"],
                "source": ["Alpha", "Gamma"],
                "target": ["Beta", "Alpha"],
                "weight": [1.0, 2.0],
                "description": ["a-b", "g-a"],
                "text_unit_ids": [["t0"], ["t0"]],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="entities",
        linked_to_type=GraphOutputTableEnum.ENTITIES,
        linked_to_id="e0",
    )

    assert sorted(row["id"] for row in result.rows) == ["e1", "e2"]


async def test_entities_filtered_by_relationships_lists_both_endpoints(tmp_path, uow):
    entities = _entities(3)
    entities.loc[0, "title"] = "Alpha"
    entities.loc[1, "title"] = "Beta"
    entities.loc[2, "title"] = "Gamma"
    write_table(tmp_path, "entities", entities)
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0"],
                "source": ["Alpha"],
                "target": ["Beta"],
                "weight": [1.0],
                "description": ["a-b"],
                "text_unit_ids": [["t0"]],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="entities",
        linked_to_type=GraphOutputTableEnum.RELATIONSHIPS,
        linked_to_id="r0",
    )

    assert sorted(row["id"] for row in result.rows) == ["e0", "e1"]


async def test_relationships_filtered_by_entities_matches_source_and_target(tmp_path, uow):
    entities = _entities(3)
    entities.loc[0, "title"] = "Alpha"
    entities.loc[1, "title"] = "Beta"
    entities.loc[2, "title"] = "Gamma"
    write_table(tmp_path, "entities", entities)
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0", "r1", "r2"],
                "source": ["Alpha", "Beta", "Gamma"],
                "target": ["Beta", "Gamma", "Alpha"],
                "weight": [1.0, 2.0, 3.0],
                "description": ["a-b", "b-g", "g-a"],
                "text_unit_ids": [["t0"], ["t1"], ["t2"]],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="relationships",
        linked_to_type=GraphOutputTableEnum.ENTITIES,
        linked_to_id="e0",
    )

    assert sorted(row["id"] for row in result.rows) == ["r0", "r2"]


# -- Linked-to filter: communities direct edges --


async def test_communities_filtered_by_entities_uses_entity_ids_list(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c10", "c20"],
                "community": [10, 20],
                "parent": ["-1", "-1"],
                "children": [[], []],
                "title": ["C10", "C20"],
                "level": [0, 0],
                "size": [2, 1],
                "entity_ids": [["e0", "e1"], ["e2"]],
                "relationship_ids": [[], []],
                "text_unit_ids": [[], []],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="communities",
        linked_to_type=GraphOutputTableEnum.ENTITIES,
        linked_to_id="e2",
    )

    assert [row["id"] for row in result.rows] == ["c20"]


async def test_community_reports_filtered_by_communities_uses_community_key(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    _write_two_documents_linked_to_two_communities(tmp_path)

    result = await _table_data(
        uow,
        table_name="community_reports",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c10",
    )

    assert [row["id"] for row in result.rows] == ["cr10"]
    assert result.total == 1


async def test_community_reports_filtered_by_communities_handles_dtype_mismatch(tmp_path, uow):
    # Regression: parquet lands `community` as int64 on `communities` but as float64 on
    # `community_reports` when a null row is present. Without string normalisation on both
    # sides, pandas returns an all-False mask and the response silently drops every row.
    write_table(tmp_path, "entities", _entities(1))
    write_table(
        tmp_path,
        "documents",
        pandas.DataFrame(
            {
                "id": ["d0"],
                "human_readable_id": [1],
                "title": ["Doc0"],
                "text_unit_ids": [["t0"]],
            }
        ),
    )
    # communities.community stays int (parquet int64).
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c10", "c20"],
                "community": [10, 20],
                "parent": ["-1", "-1"],
                "children": [[], []],
                "title": ["Comm10", "Comm20"],
                "level": [0, 0],
                "size": [2, 1],
                "entity_ids": [["e0"], ["e1"]],
                "relationship_ids": [[], []],
                "text_unit_ids": [["t0"], ["t1"]],
            }
        ),
    )
    # community_reports has a null `community` row — pandas promotes the column to float64.
    reports = pandas.DataFrame(
        {
            "id": ["cr10", "cr20", "cr_orphan"],
            "community": [10, 20, None],
            "title": ["Report10", "Report20", "Orphan"],
            "summary": ["summary 10", "summary 20", "orphan"],
        }
    )
    assert reports["community"].dtype == "float64"
    write_table(tmp_path, "community_reports", reports)

    result = await _table_data(
        uow,
        table_name="community_reports",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c10",
    )

    assert [row["id"] for row in result.rows] == ["cr10"]
    assert result.total == 1


async def test_communities_filtered_by_community_reports_handles_dtype_mismatch(tmp_path, uow):
    # Mirror of the above for the reverse direction: communities (int) filtered by a
    # community_reports pick whose `community` column is float due to a null row.
    write_table(tmp_path, "entities", _entities(1))
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c10", "c20"],
                "community": [10, 20],
                "parent": ["-1", "-1"],
                "children": [[], []],
                "title": ["Comm10", "Comm20"],
                "level": [0, 0],
                "size": [2, 1],
                "entity_ids": [["e0"], ["e1"]],
                "relationship_ids": [[], []],
                "text_unit_ids": [["t0"], ["t1"]],
            }
        ),
    )
    reports = pandas.DataFrame(
        {
            "id": ["cr10", "cr20", "cr_orphan"],
            "community": [10, 20, None],
            "title": ["Report10", "Report20", "Orphan"],
            "summary": ["summary 10", "summary 20", "orphan"],
        }
    )
    assert reports["community"].dtype == "float64"
    write_table(tmp_path, "community_reports", reports)

    result = await _table_data(
        uow,
        table_name="communities",
        linked_to_type=GraphOutputTableEnum.COMMUNITY_REPORTS,
        linked_to_id="cr10",
    )

    assert [row["id"] for row in result.rows] == ["c10"]
    assert result.total == 1


# -- Linked-to filter: hierarchy pairs (NEW) --


async def test_communities_filtered_by_communities_returns_parent_and_direct_children(
    tmp_path, uow
):
    write_table(tmp_path, "entities", _entities(1))
    # Tree: root(1) -> mid(2) -> leaf(3); unrelated(99). Asking "linked to mid" must
    # return root and leaf — the direct hierarchy neighbours, not the whole branch.
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c-root", "c-mid", "c-leaf", "c-other"],
                "community": [1, 2, 3, 99],
                "parent": ["-1", "1", "2", "-1"],
                "children": [["2"], ["3"], [], []],
                "title": ["Root", "Mid", "Leaf", "Other"],
                "level": [0, 1, 2, 0],
                "size": [10, 5, 1, 1],
                "entity_ids": [[], [], [], []],
                "relationship_ids": [[], [], [], []],
                "text_unit_ids": [[], [], [], []],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="communities",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c-mid",
    )

    assert sorted(row["id"] for row in result.rows) == ["c-leaf", "c-root"]


async def test_communities_filtered_by_communities_returns_cross_edge_neighbours(
    tmp_path, uow,
):
    # Flat hierarchy: every community is at the root, so parent/children are empty and
    # the hierarchy branch alone would return nothing. The filter must still surface
    # communities that sit on the far end of a relationship from a target-community
    # entity — that is the adjacency the visualization draws edges for. Leiden assigns
    # each entity to exactly one community per level, so communities.entity_ids are
    # disjoint; adjacency must come from the relationships table directly.
    write_table(tmp_path, "entities", _entities(5))
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0", "r1", "r2"],
                # Entity0 (in c-a) ↔ Entity2 (in c-b): a-b edge.
                # Entity1 (in c-a) ↔ Entity3 (in c-c): a-c edge.
                # Entity3 (in c-c) ↔ Entity4 (in c-c): intra-c edge (ignored for a).
                "source": ["Entity0", "Entity1", "Entity3"],
                "target": ["Entity2", "Entity3", "Entity4"],
                "description": ["a-b edge", "a-c edge", "intra c"],
                "weight": [1.0, 1.0, 1.0],
                "combined_degree": [2, 2, 2],
                "text_unit_ids": [["t0"], ["t0"], ["t0"]],
            }
        ),
    )
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c-a", "c-b", "c-c", "c-d"],
                "community": [1, 2, 3, 4],
                "parent": ["-1", "-1", "-1", "-1"],
                "children": [[], [], [], []],
                "title": ["A", "B", "C", "D"],
                "level": [0, 0, 0, 0],
                "size": [2, 1, 2, 0],
                "entity_ids": [["e0", "e1"], ["e2"], ["e3", "e4"], []],
                # Deliberately empty: we must not rely on this column for adjacency.
                "relationship_ids": [[], [], [], []],
                "text_unit_ids": [[], [], [], []],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="communities",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c-a",
    )

    assert sorted(row["id"] for row in result.rows) == ["c-b", "c-c"]
    assert result.total == 2


async def test_community_reports_filtered_by_community_reports_uses_hierarchy(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c-root", "c-mid", "c-leaf"],
                "community": [1, 2, 3],
                "parent": ["-1", "1", "2"],
                "children": [["2"], ["3"], []],
                "title": ["Root", "Mid", "Leaf"],
                "level": [0, 1, 2],
                "size": [10, 5, 1],
                "entity_ids": [[], [], []],
                "relationship_ids": [[], [], []],
                "text_unit_ids": [[], [], []],
            }
        ),
    )
    write_table(
        tmp_path,
        "community_reports",
        pandas.DataFrame(
            {
                "id": ["cr-root", "cr-mid", "cr-leaf"],
                "community": [1, 2, 3],
                "title": ["RootReport", "MidReport", "LeafReport"],
                "summary": ["r", "m", "l"],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="community_reports",
        linked_to_type=GraphOutputTableEnum.COMMUNITY_REPORTS,
        linked_to_id="cr-mid",
    )

    assert sorted(row["id"] for row in result.rows) == ["cr-leaf", "cr-root"]


# -- Linked-to filter: covariates same-subject --


async def test_covariates_filtered_by_covariates_matches_same_subject_id(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    write_table(
        tmp_path,
        "covariates",
        pandas.DataFrame(
            {
                "id": ["cv0", "cv1", "cv2"],
                "subject_id": ["Alpha", "Alpha", "Beta"],
                "subject_type": ["entity", "entity", "entity"],
                "covariate_type": ["claim", "claim", "claim"],
                "description": ["a-1", "a-2", "b-1"],
                "text_unit_ids": [["t0"], ["t0"], ["t1"]],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="covariates",
        linked_to_type=GraphOutputTableEnum.COVARIATES,
        linked_to_id="cv0",
    )

    # Same subject_id as cv0 — cv0 itself included (deliberate; the clicked row is
    # less surprising next to its siblings than hidden).
    assert sorted(row["id"] for row in result.rows) == ["cv0", "cv1"]


# -- `search_scope` restricts the search surface --


async def test_search_scope_identity_ignores_description_matches_on_entities(tmp_path, uow):
    # Default `all` scope hits entities whose description mentions "velour"; `identity` only
    # matches on id + title, so the description-only rows drop out. This mirrors the linked-to
    # picker's user ask: searching for "velour" must not surface KYIV / LASER / … that only
    # mention it in body text.
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": ["e0", "e1", "e2"],
                "title": ["VELOUR STUDIO", "KYIV", "LASER"],
                "type": ["ORG", "GEO", "SERVICE"],
                "description": [
                    "Velour studio in Kyiv",
                    "City where Velour studio operates",
                    "Velour hair removal service",
                ],
                "degree": [3, 1, 1],
                "text_unit_ids": [["t0"], ["t0"], ["t0"]],
            }
        ),
    )

    all_scope = await _table_data(uow, search="velour")
    identity_scope = await _table_data(
        uow, search="velour", search_scope=GraphTableSearchScope.IDENTITY
    )

    assert sorted(row["id"] for row in all_scope.rows) == ["e0", "e1", "e2"]
    assert [row["id"] for row in identity_scope.rows] == ["e0"]
    assert identity_scope.total == 1


async def test_search_scope_identity_also_matches_by_id(tmp_path, uow):
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": ["velour-studio", "kyiv"],
                "title": ["Alpha", "Beta"],
                "type": ["ORG", "GEO"],
                "description": ["a", "b"],
                "degree": [1, 1],
                "text_unit_ids": [["t0"], ["t0"]],
            }
        ),
    )

    result = await _table_data(
        uow, search="velour", search_scope=GraphTableSearchScope.IDENTITY
    )

    assert [row["id"] for row in result.rows] == ["velour-studio"]


async def test_search_scope_identity_on_relationships_matches_endpoints(tmp_path, uow):
    # Relationships identity surface = id + source + target.
    write_table(tmp_path, "entities", _entities(1))
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0", "r1", "r2"],
                "source": ["Velour", "Kyiv", "Laser"],
                "target": ["Kyiv", "Studio", "Velour"],
                "description": ["ignored", "velour in description", "ignored"],
                "weight": [1.0, 1.0, 1.0],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="relationships",
        search="velour",
        search_scope=GraphTableSearchScope.IDENTITY,
    )

    # r0 (source=Velour) and r2 (target=Velour) match; r1 would match only via description
    # under the default scope and must not surface here.
    assert sorted(row["id"] for row in result.rows) == ["r0", "r2"]


# -- Linked-to filter: documents ↔ text_units join lives on the documents side --


def _write_text_units_without_document_ids(output_directory):
    # Reproduces the real-world shape: graphrag's text_units.parquet in this deployment
    # has no document_ids column, so the join must route through documents.text_unit_ids.
    write_table(
        output_directory,
        "text_units",
        pandas.DataFrame(
            {
                "id": ["t0", "t1", "t2"],
                "text": ["alpha", "beta", "gamma"],
                "n_tokens": [1, 1, 1],
                "entity_ids": [[], [], []],
                "relationship_ids": [[], [], []],
                "covariate_ids": [[], [], []],
            }
        ),
    )
    write_table(
        output_directory,
        "documents",
        pandas.DataFrame(
            {
                "id": ["d0", "d1"],
                "human_readable_id": [1, 2],
                "title": ["Doc0", "Doc1"],
                "text_unit_ids": [["t0", "t1"], ["t2"]],
            }
        ),
    )


async def test_documents_filtered_by_text_units_without_document_ids_column(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    _write_text_units_without_document_ids(tmp_path)

    result = await _table_data(
        uow,
        table_name="documents",
        linked_to_type=GraphOutputTableEnum.TEXT_UNITS,
        linked_to_id="t1",
    )

    assert [row["id"] for row in result.rows] == ["d0"]
    assert result.total == 1


async def test_text_units_filtered_by_documents_without_document_ids_column(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    _write_text_units_without_document_ids(tmp_path)

    result = await _table_data(
        uow,
        table_name="text_units",
        linked_to_type=GraphOutputTableEnum.DOCUMENTS,
        linked_to_id="d0",
    )

    assert sorted(row["id"] for row in result.rows) == ["t0", "t1"]
    assert result.total == 2


# -- Linked-to filter: forbidden pairs (400) --


@pytest.mark.parametrize(
    ("subject_table", "linked_to_type"),
    [
        ("relationships", GraphOutputTableEnum.RELATIONSHIPS),
        ("text_units", GraphOutputTableEnum.TEXT_UNITS),
        ("documents", GraphOutputTableEnum.DOCUMENTS),
        ("relationships", GraphOutputTableEnum.COVARIATES),
        ("covariates", GraphOutputTableEnum.RELATIONSHIPS),
        ("communities", GraphOutputTableEnum.COVARIATES),
        ("covariates", GraphOutputTableEnum.COMMUNITIES),
        ("community_reports", GraphOutputTableEnum.COVARIATES),
        ("covariates", GraphOutputTableEnum.COMMUNITY_REPORTS),
    ],
)
async def test_forbidden_link_pair_raises_unsupported(
    tmp_path, uow, subject_table, linked_to_type
):
    # One row per touched table so the orchestrator reaches the resolver instead of
    # raising GraphNotIndexedError on a missing entities file.
    write_table(tmp_path, "entities", _entities(1))
    if subject_table != "entities":
        # Tiny stub subject table so the dataframe is not empty before dispatch.
        write_table(
            tmp_path,
            subject_table,
            pandas.DataFrame({"id": ["x0"]}),
        )

    with pytest.raises(UnsupportedError):
        await _table_data(
            uow,
            table_name=subject_table,
            linked_to_type=linked_to_type,
            linked_to_id="any",
        )


async def test_allowed_pairs_matrix_matches_the_spec():
    # A regression pin: every forbidden pair above must stay forbidden; everything
    # else in the 7x7 grid must stay allowed. The matrix is the API contract the UI
    # relies on to hide tabs.
    forbidden = {
        (GraphOutputTableEnum.RELATIONSHIPS, GraphOutputTableEnum.RELATIONSHIPS),
        (GraphOutputTableEnum.TEXT_UNITS, GraphOutputTableEnum.TEXT_UNITS),
        (GraphOutputTableEnum.DOCUMENTS, GraphOutputTableEnum.DOCUMENTS),
        (GraphOutputTableEnum.RELATIONSHIPS, GraphOutputTableEnum.COVARIATES),
        (GraphOutputTableEnum.COVARIATES, GraphOutputTableEnum.RELATIONSHIPS),
        (GraphOutputTableEnum.COMMUNITIES, GraphOutputTableEnum.COVARIATES),
        (GraphOutputTableEnum.COVARIATES, GraphOutputTableEnum.COMMUNITIES),
        (GraphOutputTableEnum.COMMUNITY_REPORTS, GraphOutputTableEnum.COVARIATES),
        (GraphOutputTableEnum.COVARIATES, GraphOutputTableEnum.COMMUNITY_REPORTS),
    }
    every_table = list(GraphOutputTableEnum)
    for subject in every_table:
        for target in every_table:
            pair_allowed = target in ALLOWED_PAIRS.get(subject, frozenset())
            if (subject, target) in forbidden:
                assert not pair_allowed, f"{subject.value}->{target.value} must be forbidden"
            else:
                assert pair_allowed, f"{subject.value}->{target.value} must be allowed"


async def test_resolvers_match_allowed_pairs_exactly():
    # Pin the dispatch table against the API contract: every allowed pair must have a
    # resolver, and no resolver may exist for a forbidden pair. A drift here would
    # either 500 on a tab the UI shows (missing resolver) or silently answer a pair
    # the UI hides (extra resolver).
    expected = {
        (subject, target)
        for subject, targets in ALLOWED_PAIRS.items()
        for target in targets
    }
    assert set(_RESOLVERS.keys()) == expected


# -- Linked-to filter: misc behavior --


async def test_linked_to_missing_target_row_yields_empty(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(3))
    write_table(
        tmp_path,
        "communities",
        pandas.DataFrame(
            {
                "id": ["c10"],
                "community": [10],
                "parent": ["-1"],
                "children": [[]],
                "title": ["C10"],
                "level": [0],
                "size": [1],
                "entity_ids": [["e0"]],
                "relationship_ids": [[]],
                "text_unit_ids": [[]],
            }
        ),
    )

    result = await _table_data(
        uow,
        table_name="communities",
        linked_to_type=GraphOutputTableEnum.ENTITIES,
        linked_to_id="does-not-exist",
    )

    assert result.rows == []
    assert result.total == 0


async def test_linked_to_and_search_both_applied(tmp_path, uow):
    write_table(tmp_path, "entities", _entities(1))
    _write_two_documents_linked_to_two_communities(tmp_path)

    # Community 10 matches by its community key; search narrows to the title "Report10".
    matches = await _table_data(
        uow,
        table_name="community_reports",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c10",
        search="Report10",
    )
    excludes = await _table_data(
        uow,
        table_name="community_reports",
        linked_to_type=GraphOutputTableEnum.COMMUNITIES,
        linked_to_id="c10",
        search="Report20",
    )

    assert [row["id"] for row in matches.rows] == ["cr10"]
    assert excludes.rows == []


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
