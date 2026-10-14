"""Tests for GraphSearchOrchestrator.

Seams, all at external boundaries:
- FakeUoW / FakeGraphRagRepo — the database.
- `_SEARCH_MAP` entries — graphrag's searchers call an LLM; the map holds direct
  references to them, so replacing the entries is the only way to run a fake searcher.
- `FakeDataReader` — graphrag's reader of the index tables from storage.
- `apply_grounding_guard` — judges the answer with a real LLM call; replaced with a
  pass-through so these tests cover the orchestrator, not the guard.
"""

import pandas
import pytest
from application.commands import RunSearch
from application.orchestrators.searching.strategies import graph_search
from application.orchestrators.searching.strategies.graph_search import (
    GraphSearchOrchestrator,
    SearchSpecification,
)
from application.results import SearchResult
from domain.enums import GraphSearchMethodEnum
from domain.errors import UnsupportedError
from graphrag.config.models.graph_rag_config import GraphRagConfig
from src.shared.models.knowledge_new import (
    GraphBasicSearchConfig,
    GraphDriftSearchConfig,
    GraphGlobalSearchConfig,
    GraphLocalSearchConfig,
)

INDEX_TABLES = {
    name: pandas.DataFrame({"id": [index]})
    for index, name in enumerate(
        ["text_units", "communities", "community_reports", "relationships", "entities"]
    )
}
COVARIATES = pandas.DataFrame({"id": [99]})


def _make_graph_rag_config() -> GraphRagConfig:
    from graphrag_llm.config import ModelConfig

    config = GraphRagConfig()
    stub = ModelConfig(model_provider="openai", model="gpt-4o", api_key="stub-key")
    config.embedding_models["default_embedding_model"] = stub.model_copy()
    config.completion_models["default_completion_model"] = stub.model_copy()
    return config


class FakeGraphRagRepo:
    def __init__(self):
        self.requested_rag_ids: list[int] = []

    async def get_config(self, rag_id: int) -> GraphRagConfig:
        self.requested_rag_ids.append(rag_id)
        return _make_graph_rag_config()


class FakeUoW:
    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_data_reader(tables: dict[str, pandas.DataFrame]):
    """A DataReader over the given tables; reading a missing one fails like graphrag does."""

    class FakeDataReader:
        def __init__(self, table_provider):
            pass

        def __getattr__(self, name):
            async def read():
                if name not in tables:
                    raise FileNotFoundError(f"{name}.parquet")
                return tables[name]

            return read

    return FakeDataReader


@pytest.fixture
def repo():
    return FakeGraphRagRepo()


@pytest.fixture
def orchestrator(repo):
    return GraphSearchOrchestrator(FakeUoW(repo))


@pytest.fixture(autouse=True)
def bypass_grounding_guard(monkeypatch):
    async def pass_through_guard(query, response, context, config, method):
        return response

    monkeypatch.setattr(graph_search, "apply_grounding_guard", pass_through_guard)


@pytest.fixture
def index_tables(monkeypatch):
    """The tables in the index storage; tests may add or remove entries."""
    tables = dict(INDEX_TABLES)
    monkeypatch.setattr(graph_search, "DataReader", _fake_data_reader(tables))
    return tables


@pytest.fixture
def searcher(monkeypatch):
    """Install a fake searcher for a method; returns the list of its calls."""

    def install(method: GraphSearchMethodEnum, answer="answer") -> list[dict]:
        calls = []

        async def fake_searcher(**kwargs):
            calls.append(kwargs)
            return answer, None

        real_spec = GraphSearchOrchestrator._SEARCH_MAP[method]
        monkeypatch.setitem(
            GraphSearchOrchestrator._SEARCH_MAP,
            method,
            SearchSpecification(
                searcher=fake_searcher,
                config_field=real_spec.config_field,
                config_model=real_spec.config_model,
                required_files=real_spec.required_files,
                optional_files=real_spec.optional_files,
                extra_kwargs=real_spec.extra_kwargs,
            ),
        )
        return calls

    return install


def _request(search_config, **overrides) -> RunSearch:
    return RunSearch(
        **{
            "rag_id": 42,
            "query": "what is the meaning?",
            "search_config": search_config,
            "embedding_api_key": "sk-emb",
            "llm_api_key": "sk-llm",
            **overrides,
        }
    )


ALL_GRAPH_TABLES = {"communities", "community_reports", "text_units", "relationships", "entities"}


@pytest.mark.parametrize(
    ("search_config", "applied_settings", "expected_tables", "expected_extra_kwargs"),
    [
        (
            GraphBasicSearchConfig(k=7, max_context_tokens=5000),
            ("basic_search", {"k": 7, "max_context_tokens": 5000}),
            {"text_units"},
            {"response_type": "Multiple Paragraphs"},
        ),
        (
            GraphLocalSearchConfig(top_k_entities=5, text_unit_prop=0.6, community_level=3),
            ("local_search", {"top_k_entities": 5, "text_unit_prop": 0.6}),
            ALL_GRAPH_TABLES,
            {"response_type": "Multiple Paragraphs", "community_level": 3},
        ),
        (
            GraphGlobalSearchConfig(
                max_context_tokens=8000,
                dynamic_search_max_level=4,
                dynamic_community_selection=True,
            ),
            ("global_search", {"max_context_tokens": 8000}),
            {"entities", "communities", "community_reports"},
            {
                "response_type": "Multiple Paragraphs",
                "community_level": 4,
                "dynamic_community_selection": True,
            },
        ),
        (
            GraphDriftSearchConfig(drift_k_followups=15, community_level=1),
            ("drift_search", {"drift_k_followups": 15}),
            ALL_GRAPH_TABLES,
            {"response_type": "Multiple Paragraphs", "community_level": 1},
        ),
    ],
    ids=["basic", "local", "global", "drift"],
)
async def test_search_runs_the_method_with_its_settings_tables_and_answer(
    orchestrator,
    repo,
    index_tables,
    searcher,
    search_config,
    applied_settings,
    expected_tables,
    expected_extra_kwargs,
):
    calls = searcher(search_config.method, answer="the answer")

    response = await orchestrator.execute(_request(search_config))

    assert response == SearchResult(result="the answer")
    assert repo.requested_rag_ids == [42]
    (call,) = calls
    assert call["query"] == "what is the meaning?"
    config_field, settings = applied_settings
    method_config = getattr(call["config"], config_field)
    assert {name: getattr(method_config, name) for name in settings} == settings
    passed_tables = {name for name in INDEX_TABLES if name in call}
    assert passed_tables == expected_tables
    assert all(call[name] is index_tables[name] for name in expected_tables)
    assert {name: call[name] for name in expected_extra_kwargs} == expected_extra_kwargs


@pytest.mark.parametrize("has_covariates", [True, False], ids=["present", "absent"])
async def test_local_search_passes_covariates_only_when_the_index_has_them(
    orchestrator, index_tables, searcher, has_covariates
):
    if has_covariates:
        index_tables["covariates"] = COVARIATES
    calls = searcher(GraphSearchMethodEnum.LOCAL)

    await orchestrator.execute(_request(GraphLocalSearchConfig()))

    assert calls[0]["covariates"] is (COVARIATES if has_covariates else None)


async def test_missing_required_table_fails_the_search(orchestrator, index_tables, searcher):
    del index_tables["text_units"]
    calls = searcher(GraphSearchMethodEnum.BASIC)

    with pytest.raises(FileNotFoundError):
        await orchestrator.execute(_request(GraphBasicSearchConfig()))

    assert calls == []


@pytest.mark.parametrize(
    ("primer_folds", "drift_k_followups", "community_reports", "expected_folds"),
    [
        (5, 20, 10, 5),
        (5, 20, 3, 3),
        (5, 2, 10, 2),
        (5, 20, 0, 1),
    ],
    ids=["within-limits", "capped-by-reports", "capped-by-followups", "never-below-one"],
)
async def test_drift_primer_folds_never_exceed_the_usable_community_reports(
    orchestrator,
    index_tables,
    searcher,
    primer_folds,
    drift_k_followups,
    community_reports,
    expected_folds,
):
    """More folds than reports leaves empty folds, which makes the primer hallucinate."""
    index_tables["community_reports"] = pandas.DataFrame({"id": range(community_reports)})
    calls = searcher(GraphSearchMethodEnum.DRIFT)

    await orchestrator.execute(
        _request(
            GraphDriftSearchConfig(primer_folds=primer_folds, drift_k_followups=drift_k_followups)
        )
    )

    assert calls[0]["config"].drift_search.primer_folds == expected_folds


async def test_request_api_keys_are_used_for_the_models(orchestrator, index_tables, searcher):
    calls = searcher(GraphSearchMethodEnum.BASIC)

    await orchestrator.execute(_request(GraphBasicSearchConfig()))

    config = calls[0]["config"]
    assert config.embedding_models["default_embedding_model"].api_key == "sk-emb"
    assert config.completion_models["default_completion_model"].api_key == "sk-llm"


async def test_unsupported_method_raises_unsupported_error(orchestrator, index_tables):
    class UnknownSearchConfig:
        method = "nonexistent_method"

        def model_dump(self):
            return {}

    with pytest.raises(UnsupportedError):
        await orchestrator.execute(_request(UnknownSearchConfig()))
