"""Tests for GraphVisualizationOrchestrator and detail orchestrators.

Seam: FakeUoW / FakeGraphRagRepo for the database. The index tables are real parquet
files in a temporary directory, read through graphrag's file storage.
"""

import pandas
import pyarrow.lib
import pytest
from application.commands import (
    GetEntityDetail,
    GetGraphVisualization,
    GetRelationshipDetail,
)
from application.graph_index_read_limits import GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES
from application.orchestrators.graph_visualization import (
    build_entity_detail,
    build_graph_visualization,
    build_relationship_detail,
)
from application.orchestrators.graph_visualization.strategies.graph import (
    EntityDetailOrchestrator,
    GraphVisualizationOrchestrator,
    RelationshipDetailOrchestrator,
)
from domain.enums import RAGStrategy
from domain.errors import (
    EntityNotFoundError,
    GraphNotIndexedError,
    GraphRagConfigNotFoundError,
    RelationshipNotFoundError,
    UnsupportedError,
)

from tests.orchestrators.graph_output_fakes import FakeGraphRagRepo, FakeUoW, write_table


@pytest.fixture
def repo(tmp_path) -> FakeGraphRagRepo:
    return FakeGraphRagRepo(tmp_path)


@pytest.fixture
def uow(repo) -> FakeUoW:
    return FakeUoW(repo)


def _sample_entities(count: int = 3) -> pandas.DataFrame:
    """Build a minimal entities DataFrame matching graphrag parquet output."""
    return pandas.DataFrame(
        {
            "id": [f"e{i}" for i in range(count)],
            "title": [f"Entity{i}" for i in range(count)],
            "type": ["PERSON", "ORG", None],
            "description": [f"desc{i}" if i < 2 else None for i in range(count)],
            "degree": list(range(count, 0, -1)),
            "community_ids": [["c0"], ["c0", "c1"], None],
        }
    )


def _sample_relationships() -> pandas.DataFrame:
    """Build a minimal relationships DataFrame matching graphrag parquet output."""
    return pandas.DataFrame(
        {
            "id": ["r0", "r1"],
            "source": ["Entity0", "Entity1"],
            "target": ["Entity1", "Entity2"],
            "description": ["knows", None],
            "weight": [1.0, 0.5],
        }
    )


@pytest.fixture
def indexed_graph(tmp_path):
    """Write the sample entities and relationships as the index output."""
    write_table(tmp_path, "entities", _sample_entities())
    write_table(tmp_path, "relationships", _sample_relationships())


# -- GraphVisualizationOrchestrator --


async def test_returns_all_graph_data(repo, uow, indexed_graph):
    result = await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=42))

    assert repo.requested_rag_ids == [42]
    assert len(result.entities) == 3
    assert len(result.relationships) == 2
    assert result.total_entities == 3
    assert result.total_relationships == 2

    entity = result.entities[0]
    assert entity.id == "e0"
    assert entity.title == "Entity0"
    assert entity.type == "PERSON"
    assert entity.degree == 3
    assert entity.community_ids == ["c0"]

    # Entity with None community_ids should get an empty list.
    assert result.entities[2].community_ids == []
    assert result.entities[2].type is None

    relationship = result.relationships[0]
    assert relationship.source == "Entity0"
    assert relationship.target == "Entity1"
    assert relationship.weight == 1.0


async def test_max_entities_limits_and_filters_relationships(uow, indexed_graph):
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, max_entities=2)
    )

    # Entities are sorted by degree desc, so Entity0 (degree=3) and Entity1 (degree=2) kept.
    assert {entity.title for entity in result.entities} == {"Entity0", "Entity1"}

    # Only the relationship where both source and target are in kept set survives.
    assert len(result.relationships) == 1
    assert result.relationships[0].source == "Entity0"
    assert result.relationships[0].target == "Entity1"

    # total_relationships counts all relationships before the entity limit filter.
    assert result.total_relationships == 2


async def test_default_keeps_the_two_hundred_highest_degree_entities(tmp_path, uow):
    entity_count = GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES + 50
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": [f"e{index}" for index in range(entity_count)],
                "title": [f"Entity{index}" for index in range(entity_count)],
                "type": ["ORG"] * entity_count,
                "degree": list(range(entity_count)),
                "community_ids": [[] for _ in range(entity_count)],
            }
        ),
    )
    write_table(tmp_path, "relationships", _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=42))

    assert GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES == 200
    assert len(result.entities) == 200
    assert min(entity.degree for entity in result.entities) == entity_count - 200
    assert result.total_entities == entity_count


async def test_max_entities_above_the_default_is_honoured(tmp_path, uow):
    entity_count = 2500
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": [f"e{index}" for index in range(entity_count)],
                "title": [f"Entity{index}" for index in range(entity_count)],
                "type": ["ORG"] * entity_count,
                "degree": [1] * entity_count,
                "community_ids": [[] for _ in range(entity_count)],
            }
        ),
    )
    write_table(tmp_path, "relationships", _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, max_entities=2100)
    )

    assert len(result.entities) == 2100


async def test_missing_degree_and_weight_get_defaults(tmp_path, uow):
    entities = _sample_entities()
    entities["degree"] = [3.0, None, 1.0]
    relationships = _sample_relationships()
    relationships["weight"] = [None, 0.5]
    write_table(tmp_path, "entities", entities)
    write_table(tmp_path, "relationships", relationships)

    result = await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=42))

    degrees = {entity.title: entity.degree for entity in result.entities}
    assert degrees["Entity1"] == 0
    weights = {relationship.id: relationship.weight for relationship in result.relationships}
    assert weights["r0"] == 1.0


# -- Search filter --


async def test_search_filters_entities_by_title(uow, indexed_graph):
    """Search returns only the matched entity and its direct neighbours."""
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="Entity0")
    )

    # Entity0 matched directly; Entity1 is connected via r0 (Entity0 -> Entity1).
    assert {entity.title for entity in result.entities} == {"Entity0", "Entity1"}

    # Only the relationship between Entity0 and Entity1 survives.
    assert len(result.relationships) == 1
    assert result.relationships[0].source == "Entity0"

    # Totals reflect the full unfiltered graph.
    assert result.total_entities == 3
    assert result.total_relationships == 2


async def test_search_is_case_insensitive(uow, indexed_graph):
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="entity0")
    )

    assert "Entity0" in {entity.title for entity in result.entities}


@pytest.mark.parametrize("search", ["C++", "(", "[a-z]", ".*", "\\"])
async def test_search_matches_regex_characters_literally(tmp_path, uow, search):
    entities = pandas.DataFrame(
        {
            "id": ["e0", "e1"],
            "title": [f"Uses {search} here", "Plain title"],
            "type": ["ORG", "ORG"],
            "degree": [1, 1],
            "community_ids": [[], []],
        }
    )
    write_table(tmp_path, "entities", entities)
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame({"id": [], "source": [], "target": [], "weight": []}),
    )

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search=search)
    )

    assert [entity.title for entity in result.entities] == [f"Uses {search} here"]


async def test_search_does_not_match_missing_titles(tmp_path, uow):
    entities = _sample_entities()
    entities["title"] = ["Entity0", None, "Entity2"]
    write_table(tmp_path, "entities", entities)
    write_table(tmp_path, "relationships", _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="nan")
    )

    assert result.entities == []


async def test_search_no_match_returns_empty(uow, indexed_graph):
    """When search matches nothing, entities and relationships are empty but totals are full."""
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="nonexistent")
    )

    assert result.entities == []
    assert result.relationships == []
    assert result.total_entities == 3
    assert result.total_relationships == 2


async def test_search_combined_with_max_entities(uow, indexed_graph):
    """max_entities is applied after the search filter."""
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="Entity", max_entities=1)
    )

    assert [entity.title for entity in result.entities] == ["Entity0"]  # highest degree


async def test_search_keeps_low_degree_matches_ahead_of_high_degree_neighbours(tmp_path, uow):
    # "Needle" matches but has the lowest degree; its four neighbours do not match.
    neighbour_titles = [f"Hub{index}" for index in range(4)]
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(
            {
                "id": ["needle", "hub0", "hub1", "hub2", "hub3", "loner"],
                "title": ["Needle", *neighbour_titles, "Loner"],
                "type": ["ORG"] * 6,
                "degree": [1, 50, 40, 30, 20, 99],
                "community_ids": [[] for _ in range(6)],
            }
        ),
    )
    write_table(
        tmp_path,
        "relationships",
        pandas.DataFrame(
            {
                "id": ["r0", "r1", "r2", "r3", "r4"],
                "source": ["Needle", "Needle", "Hub2", "Hub3", "Hub0"],
                "target": ["Hub0", "Hub1", "Needle", "Needle", "Hub1"],
                "weight": [1.0] * 5,
            }
        ),
    )

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="needle", max_entities=3)
    )

    # The match comes first, then the highest-degree neighbours fill the rest of the cap.
    assert [entity.title for entity in result.entities] == ["Needle", "Hub0", "Hub1"]
    assert {relationship.id for relationship in result.relationships} == {"r0", "r1", "r4"}
    # Totals describe the whole graph, before the search and the cap.
    assert result.total_entities == 6
    assert result.total_relationships == 5


@pytest.mark.parametrize("search", [None, ""])
async def test_absent_search_skips_filter(uow, indexed_graph, search):
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search=search)
    )

    assert len(result.entities) == 3


# -- Not indexed / no RAG --


async def test_empty_entities_raises_graph_not_indexed(tmp_path, uow):
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame(columns=["id", "title", "type", "description", "degree"]),
    )
    write_table(tmp_path, "relationships", _sample_relationships())

    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=99))


async def test_missing_tables_raise_graph_not_indexed(uow):
    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=99))


async def test_missing_relationships_table_raises_graph_not_indexed(tmp_path, uow):
    write_table(tmp_path, "entities", _sample_entities())

    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=99))


async def test_corrupt_table_is_not_reported_as_not_indexed(tmp_path, uow):
    (tmp_path / "entities.parquet").write_bytes(b"not a parquet file")
    write_table(tmp_path, "relationships", _sample_relationships())

    # Both tables are read in a TaskGroup, so the decoding error arrives grouped.
    with pytest.raises(ExceptionGroup) as raised:
        await GraphVisualizationOrchestrator(uow).execute(GetGraphVisualization(rag_id=99))

    assert raised.group_contains(pyarrow.lib.ArrowInvalid)
    assert not raised.group_contains(GraphNotIndexedError)


@pytest.mark.parametrize(
    "command",
    [
        GetGraphVisualization(rag_id=7),
        GetEntityDetail(rag_id=7, entity_id="e0"),
        GetRelationshipDetail(rag_id=7, relationship_id="r0"),
    ],
    ids=["visualization", "entity-detail", "relationship-detail"],
)
async def test_unknown_rag_raises_config_not_found(command):
    uow = FakeUoW(FakeGraphRagRepo(output_directory=None))
    orchestrator_class = {
        GetGraphVisualization: GraphVisualizationOrchestrator,
        GetEntityDetail: EntityDetailOrchestrator,
        GetRelationshipDetail: RelationshipDetailOrchestrator,
    }[type(command)]

    with pytest.raises(GraphRagConfigNotFoundError):
        await orchestrator_class(uow).execute(command)


def test_visualization_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_graph_visualization(RAGStrategy.NAIVE, uow)


# -- EntityDetailOrchestrator --


async def test_entity_detail_returns_description(uow, indexed_graph):
    result = await EntityDetailOrchestrator(uow).execute(GetEntityDetail(rag_id=42, entity_id="e0"))

    assert result.description == "desc0"


async def test_entity_detail_reads_only_the_entities_table(tmp_path, uow):
    # No relationships table: the entity lookup must not need it.
    write_table(tmp_path, "entities", _sample_entities())

    result = await EntityDetailOrchestrator(uow).execute(GetEntityDetail(rag_id=42, entity_id="e1"))

    assert result.description == "desc1"


async def test_entity_detail_returns_none_for_missing_description(uow, indexed_graph):
    result = await EntityDetailOrchestrator(uow).execute(GetEntityDetail(rag_id=42, entity_id="e2"))

    assert result.description is None


async def test_entity_detail_raises_not_found(uow, indexed_graph):
    with pytest.raises(EntityNotFoundError):
        await EntityDetailOrchestrator(uow).execute(
            GetEntityDetail(rag_id=42, entity_id="nonexistent")
        )


async def test_entity_detail_raises_not_indexed_without_entities_table(uow):
    with pytest.raises(GraphNotIndexedError):
        await EntityDetailOrchestrator(uow).execute(GetEntityDetail(rag_id=42, entity_id="e0"))


def test_entity_detail_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_entity_detail(RAGStrategy.NAIVE, uow)


# -- RelationshipDetailOrchestrator --


async def test_relationship_detail_returns_description(uow, indexed_graph):
    result = await RelationshipDetailOrchestrator(uow).execute(
        GetRelationshipDetail(rag_id=42, relationship_id="r0")
    )

    assert result.description == "knows"


async def test_relationship_detail_reads_only_the_relationships_table(tmp_path, uow):
    write_table(tmp_path, "relationships", _sample_relationships())

    result = await RelationshipDetailOrchestrator(uow).execute(
        GetRelationshipDetail(rag_id=42, relationship_id="r0")
    )

    assert result.description == "knows"


async def test_relationship_detail_returns_none_for_missing_description(uow, indexed_graph):
    result = await RelationshipDetailOrchestrator(uow).execute(
        GetRelationshipDetail(rag_id=42, relationship_id="r1")
    )

    assert result.description is None


async def test_relationship_detail_raises_not_found(uow, indexed_graph):
    with pytest.raises(RelationshipNotFoundError):
        await RelationshipDetailOrchestrator(uow).execute(
            GetRelationshipDetail(rag_id=42, relationship_id="nonexistent")
        )


def test_relationship_detail_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_relationship_detail(RAGStrategy.NAIVE, uow)
