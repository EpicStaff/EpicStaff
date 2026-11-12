"""Tests for GraphVisualizationOrchestrator and detail orchestrators.

Seams: FakeUoW / FakeGraphRagRepo for the database, and graphrag's DataReader,
which reads the index tables from storage.
"""

import pandas
import pytest
from application.commands import (
    GetEntityDetail,
    GetGraphVisualization,
    GetRelationshipDetail,
)
from application.orchestrators.graph_visualization import (
    build_entity_detail,
    build_graph_visualization,
    build_relationship_detail,
)
from application.orchestrators.graph_visualization.strategies import graph as graph_module
from application.orchestrators.graph_visualization.strategies.graph import (
    EntityDetailOrchestrator,
    GraphVisualizationOrchestrator,
    RelationshipDetailOrchestrator,
)
from domain.enums import RAGStrategy
from domain.errors import (
    EntityNotFoundError,
    GraphNotIndexedError,
    RelationshipNotFoundError,
    UnsupportedError,
)
from graphrag.config.models.graph_rag_config import GraphRagConfig


class FakeGraphRagRepo:
    def __init__(self):
        self.requested_rag_ids: list[int] = []

    async def get_config(self, rag_id: int, slot=None) -> GraphRagConfig:
        self.requested_rag_ids.append(rag_id)
        return GraphRagConfig()


class FakeUoW:
    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def repo() -> FakeGraphRagRepo:
    return FakeGraphRagRepo()


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


def _patch_reader(monkeypatch, entities, relationships):
    """Replace the DataReader with a fake that returns the given DataFrames."""

    class FakeDataReader:
        def __init__(self, table_provider):
            pass

        async def entities(self):
            return entities

        async def relationships(self):
            return relationships

    monkeypatch.setattr(graph_module, "DataReader", FakeDataReader)


# -- GraphVisualizationOrchestrator --


async def test_returns_all_graph_data(repo, uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42)
    )

    assert repo.requested_rag_ids == [42]
    assert len(result.entities) == 3
    assert len(result.relationships) == 2
    assert result.total_entities == 3
    assert result.total_relationships == 2

    # Spot-check entity mapping — description is excluded from visualization.
    entity = result.entities[0]
    assert entity.id == "e0"
    assert entity.title == "Entity0"
    assert entity.type == "PERSON"
    assert entity.degree == 3
    assert entity.community_ids == ["c0"]
    assert not hasattr(entity, "description")

    # Entity with None community_ids should get an empty list.
    assert result.entities[2].community_ids == []
    assert result.entities[2].type is None

    # Spot-check relationship mapping — description is excluded from visualization.
    relationship = result.relationships[0]
    assert relationship.source == "Entity0"
    assert relationship.target == "Entity1"
    assert relationship.weight == 1.0
    assert not hasattr(relationship, "description")


async def test_max_entities_limits_and_filters_relationships(repo, uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, max_entities=2)
    )

    # Entities are sorted by degree desc, so Entity0 (degree=3) and Entity1 (degree=2) kept.
    assert len(result.entities) == 2
    kept_titles = {e.title for e in result.entities}
    assert kept_titles == {"Entity0", "Entity1"}

    # Only the relationship where both source and target are in kept set survives.
    assert len(result.relationships) == 1
    assert result.relationships[0].source == "Entity0"
    assert result.relationships[0].target == "Entity1"

    # total_relationships counts all relationships before the entity limit filter.
    assert result.total_relationships == 2


# -- Search filter --


async def test_search_filters_entities_by_title(uow, monkeypatch):
    """Search returns only the matched entity and its direct neighbours."""
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="Entity0")
    )

    # Entity0 matched directly; Entity1 is connected via r0 (Entity0 -> Entity1).
    titles = {e.title for e in result.entities}
    assert titles == {"Entity0", "Entity1"}

    # Only the relationship between Entity0 and Entity1 survives.
    assert len(result.relationships) == 1
    assert result.relationships[0].source == "Entity0"

    # Totals reflect the full unfiltered graph.
    assert result.total_entities == 3
    assert result.total_relationships == 2


async def test_search_is_case_insensitive(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="entity0")
    )

    titles = {e.title for e in result.entities}
    assert "Entity0" in titles


async def test_search_no_match_returns_empty(uow, monkeypatch):
    """When search matches nothing, entities and relationships are empty but totals are full."""
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="nonexistent")
    )

    assert result.entities == []
    assert result.relationships == []
    assert result.total_entities == 3
    assert result.total_relationships == 2


async def test_search_combined_with_max_entities(uow, monkeypatch):
    """max_entities is applied after the search filter."""
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    # Search "Entity" matches all 3 entities plus their neighbours (all 3).
    # max_entities=1 then keeps only the top-1 by degree.
    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="Entity", max_entities=1)
    )

    assert len(result.entities) == 1
    assert result.entities[0].title == "Entity0"  # highest degree


async def test_search_none_skips_filter(uow, monkeypatch):
    """When search is None, all entities are returned (existing behavior)."""
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search=None)
    )

    assert len(result.entities) == 3


async def test_search_empty_string_skips_filter(uow, monkeypatch):
    """An empty search string behaves the same as None."""
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42, search="")
    )

    assert len(result.entities) == 3


async def test_empty_entities_raises_graph_not_indexed(uow, monkeypatch):
    _patch_reader(
        monkeypatch,
        pandas.DataFrame(columns=["id", "title", "type", "description", "degree"]),
        _sample_relationships(),
    )

    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(
            GetGraphVisualization(rag_id=99)
        )


async def test_file_not_found_raises_graph_not_indexed(uow, monkeypatch):
    """When parquet files are missing, the reader raises FileNotFoundError."""

    class BrokenReader:
        def __init__(self, table_provider):
            pass

        async def entities(self):
            raise FileNotFoundError("entities.parquet not found")

        async def relationships(self):
            raise FileNotFoundError

    monkeypatch.setattr(graph_module, "DataReader", BrokenReader)

    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(
            GetGraphVisualization(rag_id=99)
        )


def test_visualization_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_graph_visualization(RAGStrategy.NAIVE, uow)


# -- EntityDetailOrchestrator --


async def test_entity_detail_returns_description(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await EntityDetailOrchestrator(uow).execute(
        GetEntityDetail(rag_id=42, entity_id="e0")
    )

    assert result.description == "desc0"


async def test_entity_detail_returns_none_for_missing_description(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await EntityDetailOrchestrator(uow).execute(
        GetEntityDetail(rag_id=42, entity_id="e2")
    )

    assert result.description is None


async def test_entity_detail_raises_not_found(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    with pytest.raises(EntityNotFoundError):
        await EntityDetailOrchestrator(uow).execute(
            GetEntityDetail(rag_id=42, entity_id="nonexistent")
        )


def test_entity_detail_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_entity_detail(RAGStrategy.NAIVE, uow)


# -- RelationshipDetailOrchestrator --


async def test_relationship_detail_returns_description(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await RelationshipDetailOrchestrator(uow).execute(
        GetRelationshipDetail(rag_id=42, relationship_id="r0")
    )

    assert result.description == "knows"


async def test_relationship_detail_returns_none_for_missing_description(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    result = await RelationshipDetailOrchestrator(uow).execute(
        GetRelationshipDetail(rag_id=42, relationship_id="r1")
    )

    assert result.description is None


async def test_relationship_detail_raises_not_found(uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships())

    with pytest.raises(RelationshipNotFoundError):
        await RelationshipDetailOrchestrator(uow).execute(
            GetRelationshipDetail(rag_id=42, relationship_id="nonexistent")
        )


def test_relationship_detail_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_relationship_detail(RAGStrategy.NAIVE, uow)
