"""Tests for GraphMetricsOrchestrator.

Seams: FakeUoW / FakeGraphRagRepo for the database, and graphrag's `DataReader`, which
reads the index tables from storage.
"""

import pandas
import pytest
from application.commands import GetMetrics
from application.orchestrators.metrics import build_metrics
from application.orchestrators.metrics.strategies import graph_metrics
from application.orchestrators.metrics.strategies.graph_metrics import GraphMetricsOrchestrator
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError
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


def _index_with_text_units(monkeypatch, text_units: pandas.DataFrame):
    class FakeDataReader:
        def __init__(self, table_provider):
            pass

        async def text_units(self):
            return text_units

    monkeypatch.setattr(graph_metrics, "DataReader", FakeDataReader)


@pytest.mark.parametrize(
    ("token_counts", "expected_total", "expected_average"),
    [
        ([100, 200, 300], 3, 200.0),
        ([100, None, 300], 3, 200.0),
        ([], 0, 0.0),
    ],
    ids=["all-counted", "missing-counts-ignored-in-average", "empty-index"],
)
async def test_metrics_are_computed_from_the_rags_text_units(
    repo, uow, monkeypatch, token_counts, expected_total, expected_average
):
    _index_with_text_units(monkeypatch, pandas.DataFrame({"n_tokens": token_counts}))

    result = await GraphMetricsOrchestrator(uow).execute(GetMetrics(rag_id=7))

    assert repo.requested_rag_ids == [7]
    assert (result.total_chunks, result.avg_chunk_size) == (expected_total, expected_average)


def test_metrics_are_unsupported_for_naive_rags(uow):
    with pytest.raises(UnsupportedError):
        build_metrics(RAGStrategy.NAIVE, uow)
