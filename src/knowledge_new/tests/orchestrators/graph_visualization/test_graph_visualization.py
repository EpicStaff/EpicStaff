"""Tests for GraphVisualizationOrchestrator.

Seams: FakeUoW / FakeGraphRagRepo for the database, and graphrag's DataReader,
which reads the index tables from storage.
"""

import pandas
import pytest
from application.commands import GetGraphVisualization
from application.orchestrators.graph_visualization import build_graph_visualization
from application.orchestrators.graph_visualization.strategies import graph as graph_module
from application.orchestrators.graph_visualization.strategies.graph import (
    GraphVisualizationOrchestrator,
)
from domain.enums import RAGStrategy
from domain.errors import GraphNotIndexedError, UnsupportedError
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


def _sample_communities() -> pandas.DataFrame:
    """Build a minimal communities DataFrame matching graphrag parquet output."""
    return pandas.DataFrame(
        {
            "id": ["c0", "c1"],
            "title": ["Community 0", "Community 1"],
            "level": [0, 1],
            "size": [10, 5],
            "entity_ids": [["e0", "e1"], ["e2"]],
        }
    )


def _patch_reader(monkeypatch, entities, relationships, communities):
    """Replace the DataReader with a fake that returns the given DataFrames."""

    class FakeDataReader:
        def __init__(self, table_provider):
            pass

        async def entities(self):
            return entities

        async def relationships(self):
            return relationships

        async def communities(self):
            return communities

    monkeypatch.setattr(graph_module, "DataReader", FakeDataReader)


async def test_returns_all_graph_data(repo, uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships(), _sample_communities())

    result = await GraphVisualizationOrchestrator(uow).execute(
        GetGraphVisualization(rag_id=42)
    )

    assert repo.requested_rag_ids == [42]
    assert len(result.entities) == 3
    assert len(result.relationships) == 2
    assert len(result.communities) == 2

    # Spot-check entity mapping.
    entity = result.entities[0]
    assert entity.id == "e0"
    assert entity.title == "Entity0"
    assert entity.type == "PERSON"
    assert entity.description == "desc0"
    assert entity.degree == 3
    assert entity.community_ids == ["c0"]

    # Entity with None community_ids should get an empty list.
    assert result.entities[2].community_ids == []
    assert result.entities[2].type is None
    assert result.entities[2].description is None

    # Spot-check relationship mapping.
    relationship = result.relationships[0]
    assert relationship.source == "Entity0"
    assert relationship.target == "Entity1"
    assert relationship.weight == 1.0

    # Spot-check community mapping.
    community = result.communities[0]
    assert community.title == "Community 0"
    assert community.level == 0
    assert community.size == 10
    assert community.entity_ids == ["e0", "e1"]


async def test_max_entities_limits_and_filters_relationships(repo, uow, monkeypatch):
    _patch_reader(monkeypatch, _sample_entities(), _sample_relationships(), _sample_communities())

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


async def test_empty_entities_raises_graph_not_indexed(uow, monkeypatch):
    _patch_reader(
        monkeypatch,
        pandas.DataFrame(columns=["id", "title", "type", "description", "degree"]),
        _sample_relationships(),
        _sample_communities(),
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

        async def communities(self):
            raise FileNotFoundError

    monkeypatch.setattr(graph_module, "DataReader", BrokenReader)

    with pytest.raises(GraphNotIndexedError):
        await GraphVisualizationOrchestrator(uow).execute(
            GetGraphVisualization(rag_id=99)
        )


def test_visualization_is_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_graph_visualization(RAGStrategy.NAIVE, uow)
