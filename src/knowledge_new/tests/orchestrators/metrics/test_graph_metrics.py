"""Tests for GraphMetricsOrchestrator.on_execute() and build_metrics().

Seams:
- FakeGraphRagRepo / FakeUoW — in-memory replacements for DB access.
- monkeypatch on GraphMetricsOrchestrator._read_text_units — avoids graphrag storage;
  the orchestrator only cares about the returned text_units DataFrame.
"""

import pandas
import pytest
from application.commands import GetMetrics
from application.orchestrators.metrics import build_metrics
from application.orchestrators.metrics.strategies.graph_metrics import (
    GraphMetricsOrchestrator,
)
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError


class FakeGraphRagRepo:
    def __init__(self):
        self.get_config_calls: list[int] = []

    async def get_config(self, rag_id: int, slot=None):
        self.get_config_calls.append(rag_id)
        return object()  # opaque; _read_text_units is patched


class FakeUoW:
    def __init__(self, repo: FakeGraphRagRepo):
        self._repo = repo

    @property
    def graph_rag_repo(self) -> FakeGraphRagRepo:
        return self._repo

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


def _patch_text_units(monkeypatch, df: pandas.DataFrame):
    async def fake_read(config):
        return df

    monkeypatch.setattr(
        GraphMetricsOrchestrator, "_read_text_units", staticmethod(fake_read)
    )


@pytest.mark.asyncio
async def test_metrics_computed_from_text_units(uow, monkeypatch):
    _patch_text_units(monkeypatch, pandas.DataFrame({"n_tokens": [100, 200, 300]}))

    result = await GraphMetricsOrchestrator(uow).execute(GetMetrics(rag_id=7))

    assert result.total_chunks == 3
    assert result.avg_chunk_size == 200.0


@pytest.mark.asyncio
async def test_metrics_ignores_null_token_counts(uow, monkeypatch):
    _patch_text_units(monkeypatch, pandas.DataFrame({"n_tokens": [100, None, 300]}))

    result = await GraphMetricsOrchestrator(uow).execute(GetMetrics(rag_id=1))

    assert result.total_chunks == 3
    assert result.avg_chunk_size == 200.0


@pytest.mark.asyncio
async def test_empty_text_units_returns_zeros(uow, monkeypatch):
    _patch_text_units(monkeypatch, pandas.DataFrame({"n_tokens": []}))

    result = await GraphMetricsOrchestrator(uow).execute(GetMetrics(rag_id=1))

    assert result.total_chunks == 0
    assert result.avg_chunk_size == 0.0


@pytest.mark.asyncio
async def test_get_config_called_with_rag_id(repo, uow, monkeypatch):
    _patch_text_units(monkeypatch, pandas.DataFrame({"n_tokens": [10]}))

    await GraphMetricsOrchestrator(uow).execute(GetMetrics(rag_id=42))

    assert repo.get_config_calls == [42]


def test_build_metrics_graph(uow):
    assert isinstance(build_metrics(RAGStrategy.GRAPH, uow), GraphMetricsOrchestrator)


def test_build_metrics_unsupported_naive(uow):
    with pytest.raises(UnsupportedError):
        build_metrics(RAGStrategy.NAIVE, uow)
