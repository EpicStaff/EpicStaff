"""Tests for GraphSearch.on_execute().

Seams used:
- FakeGraphRagRepo / FakeUoW  — in-memory replacements for DB access.
- monkeypatch.setitem(GraphSearch._SEARCH_MAP, method, spec) — the _SEARCH_MAP is built
  at import time with direct references to graphrag functions; patching the module-level
  names has no effect on what's already stored.  Replacing map entries is the only seam
  that actually runs our fake searchers.
- monkeypatch.setattr(GraphSearch, '_resolve_files', ...) — avoids filesystem / graphrag
  storage entirely.
"""

import pandas
import pytest
from application.orchestrators.searching.strategies.graph_search import (
    GraphSearchOrchestrator,
    SearchSpecification,
)
from domain.enums import GraphSearchMethodEnum
from domain.errors import UnsupportedError
from application.results import SearchResult
from domain.models import SearchRequest
from graphrag.config.models.graph_rag_config import GraphRagConfig
from src.shared.models.knowledge_new import (
    GraphBasicSearchConfig,
    GraphDriftSearchConfig,
    GraphGlobalSearchConfig,
    GraphLocalSearchConfig,
)


class FakeGraphRagRepo:
    """Returns a real (default) GraphRagConfig; records get_config calls."""

    def __init__(self):
        self.get_config_calls: list[int] = []

    async def get_config(self, rag_id: int) -> GraphRagConfig:
        self.get_config_calls.append(rag_id)
        return GraphRagConfig()


class FakeUoW:
    """Re-enterable async context manager (GraphSearch enters it once in on_execute)."""

    def __init__(self, repo: FakeGraphRagRepo):
        self._repo = repo

    @property
    def graph_rag_repo(self) -> FakeGraphRagRepo:
        return self._repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_fake_searcher(return_value):
    """Return an async searcher that records every call and returns a fixed value."""

    async def fake_searcher(**kwargs):
        fake_searcher.calls.append(kwargs)
        return (return_value, None)  # searcher contract: (result, context)

    fake_searcher.calls = []
    return fake_searcher


_FAKE_TEXT_UNITS = pandas.DataFrame({"id": [1], "text": ["unit-1"]})
_FAKE_COMMUNITIES = pandas.DataFrame({"id": [10], "level": [1]})
_FAKE_COMMUNITY_REPORTS = pandas.DataFrame({"id": [10], "summary": ["report-1"]})
_FAKE_RELATIONSHIPS = pandas.DataFrame({"id": [20], "source": ["a"], "target": ["b"]})
_FAKE_ENTITIES = pandas.DataFrame({"id": [30], "name": ["ent-1"]})
_FAKE_COVARIATES = pandas.DataFrame({"id": [40], "subject_id": ["30"]})


def _make_spec_for(method: GraphSearchMethodEnum, fake_searcher):
    """Build a SearchSpecification whose searcher is our fake, mirroring the real spec."""
    real_spec = GraphSearchOrchestrator._SEARCH_MAP[method]
    return SearchSpecification(
        searcher=fake_searcher,
        config_field=real_spec.config_field,
        config_model=real_spec.config_model,
        required_files=real_spec.required_files,
        optional_files=real_spec.optional_files,
        extra_kwargs=real_spec.extra_kwargs,
    )


@pytest.fixture()
def repo():
    return FakeGraphRagRepo()


@pytest.fixture()
def uow(repo):
    return FakeUoW(repo)


@pytest.mark.parametrize(
    "method, search_config, expected_result",
    [
        (
            GraphSearchMethodEnum.BASIC,
            GraphBasicSearchConfig(k=7, max_context_tokens=5000),
            "basic answer",
        ),
        (
            GraphSearchMethodEnum.LOCAL,
            GraphLocalSearchConfig(text_unit_prop=0.6, top_k_entities=5),
            "local answer",
        ),
        (
            GraphSearchMethodEnum.GLOBAL,
            GraphGlobalSearchConfig(max_context_tokens=8000),
            "global answer",
        ),
        (
            GraphSearchMethodEnum.DRIFT,
            GraphDriftSearchConfig(drift_k_followups=15),
            "drift answer",
        ),
    ],
)
async def test_happy_path_correct_searcher_invoked(
    method, search_config, expected_result, uow, monkeypatch
):
    """Correct searcher is invoked; response.result == searcher's result."""
    fake = make_fake_searcher(expected_result)
    monkeypatch.setitem(GraphSearchOrchestrator._SEARCH_MAP, method, _make_spec_for(method, fake))

    async def fake_resolve_files(config, required_files, optional_files=None):
        files = {}
        all_fakes = {
            "text_units": _FAKE_TEXT_UNITS,
            "communities": _FAKE_COMMUNITIES,
            "community_reports": _FAKE_COMMUNITY_REPORTS,
            "relationships": _FAKE_RELATIONSHIPS,
            "entities": _FAKE_ENTITIES,
        }
        for name in required_files:
            files[name] = all_fakes[name]
        return files

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=42,
        query="what is the meaning?",
        search_config=search_config,
    )

    response = await GraphSearchOrchestrator(uow).on_execute(request)

    assert response == SearchResult(result=expected_result)
    assert response.result == expected_result
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "method, search_config",
    [
        (GraphSearchMethodEnum.BASIC, GraphBasicSearchConfig()),
        (GraphSearchMethodEnum.LOCAL, GraphLocalSearchConfig()),
        (GraphSearchMethodEnum.GLOBAL, GraphGlobalSearchConfig()),
        (GraphSearchMethodEnum.DRIFT, GraphDriftSearchConfig()),
    ],
)
async def test_query_and_config_are_forwarded_to_searcher(method, search_config, uow, monkeypatch):
    """query kwarg and config are passed through to the searcher."""
    fake = make_fake_searcher("result")
    monkeypatch.setitem(GraphSearchOrchestrator._SEARCH_MAP, method, _make_spec_for(method, fake))

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=1,
        query="my search query",
        search_config=search_config,
    )

    await GraphSearchOrchestrator(uow).on_execute(request)

    assert len(fake.calls) == 1
    call_kwargs = fake.calls[0]
    assert call_kwargs["query"] == "my search query"
    assert isinstance(call_kwargs["config"], GraphRagConfig)


@pytest.mark.parametrize(
    "method, search_config",
    [
        (GraphSearchMethodEnum.BASIC, GraphBasicSearchConfig()),
        (GraphSearchMethodEnum.LOCAL, GraphLocalSearchConfig()),
        (GraphSearchMethodEnum.GLOBAL, GraphGlobalSearchConfig()),
        (GraphSearchMethodEnum.DRIFT, GraphDriftSearchConfig()),
    ],
)
async def test_extra_kwargs_forwarded_to_searcher(method, search_config, uow, monkeypatch):
    """extra_kwargs defined in the spec reach the searcher as keyword arguments."""
    fake = make_fake_searcher("result")
    monkeypatch.setitem(GraphSearchOrchestrator._SEARCH_MAP, method, _make_spec_for(method, fake))

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(rag_id=1, query="q", search_config=search_config)
    await GraphSearchOrchestrator(uow).on_execute(request)

    real_extra_kwargs = GraphSearchOrchestrator._SEARCH_MAP[method].extra_kwargs
    call_kwargs = fake.calls[0]
    for key, value in real_extra_kwargs.items():
        assert call_kwargs[key] == value, f"Expected extra_kwarg {key}={value!r}"


async def test_search_config_validated_and_set_on_graphrag_config(uow, monkeypatch):
    """search_config values flow into the graphrag config field via model_validate + setattr."""
    received_configs = []

    async def capture_searcher(**kwargs):
        received_configs.append(kwargs["config"])
        return ("result", None)

    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.BASIC,
        _make_spec_for(GraphSearchMethodEnum.BASIC, capture_searcher),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=1,
        query="q",
        search_config=GraphBasicSearchConfig(k=99, max_context_tokens=1234),
    )
    await GraphSearchOrchestrator(uow).on_execute(request)

    assert len(received_configs) == 1
    config = received_configs[0]
    # The basic_search field on the config must reflect the request's k and max_context_tokens.
    assert config.basic_search.k == 99
    assert config.basic_search.max_context_tokens == 1234


async def test_search_config_validated_and_set_on_graphrag_config_local(uow, monkeypatch):
    """LocalSearchConfig values are validated into LocalSearchConfig and set on the config."""
    received_configs = []

    async def capture_searcher(**kwargs):
        received_configs.append(kwargs["config"])
        return ("result", None)

    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.LOCAL,
        _make_spec_for(GraphSearchMethodEnum.LOCAL, capture_searcher),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=1,
        query="q",
        search_config=GraphLocalSearchConfig(top_k_entities=7, text_unit_prop=0.8),
    )
    await GraphSearchOrchestrator(uow).on_execute(request)

    config = received_configs[0]
    assert config.local_search.top_k_entities == 7
    assert config.local_search.text_unit_prop == 0.8


@pytest.mark.parametrize(
    "method, search_config, required_file_names",
    [
        (
            GraphSearchMethodEnum.BASIC,
            GraphBasicSearchConfig(),
            ["text_units"],
        ),
        (
            GraphSearchMethodEnum.GLOBAL,
            GraphGlobalSearchConfig(),
            ["entities", "communities", "community_reports"],
        ),
        (
            GraphSearchMethodEnum.DRIFT,
            GraphDriftSearchConfig(),
            ["communities", "community_reports", "text_units", "relationships", "entities"],
        ),
    ],
)
async def test_required_files_forwarded_as_searcher_kwargs(
    method, search_config, required_file_names, uow, monkeypatch
):
    """Resolved files are passed as kwargs matching the required_files names."""
    fake = make_fake_searcher("result")
    monkeypatch.setitem(GraphSearchOrchestrator._SEARCH_MAP, method, _make_spec_for(method, fake))

    fake_dfs = {name: pandas.DataFrame({"id": [i]}) for i, name in enumerate(required_file_names)}

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: fake_dfs[n] for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(rag_id=1, query="q", search_config=search_config)
    await GraphSearchOrchestrator(uow).on_execute(request)

    call_kwargs = fake.calls[0]
    for name in required_file_names:
        assert name in call_kwargs, f"Expected file kwarg '{name}' in searcher call"
        assert call_kwargs[name] is fake_dfs[name]


async def test_local_search_with_covariates_present(uow, monkeypatch):
    """When _resolve_files returns covariates, it is forwarded to the searcher."""
    fake = make_fake_searcher("local result")
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.LOCAL,
        _make_spec_for(GraphSearchMethodEnum.LOCAL, fake),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        files = {n: pandas.DataFrame() for n in required_files}
        if optional_files:
            for name in optional_files:
                files[name] = _FAKE_COVARIATES
        return files

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=1,
        query="local query",
        search_config=GraphLocalSearchConfig(),
    )
    await GraphSearchOrchestrator(uow).on_execute(request)

    call_kwargs = fake.calls[0]
    assert "covariates" in call_kwargs
    assert call_kwargs["covariates"] is _FAKE_COVARIATES


async def test_local_search_without_covariates(uow, monkeypatch):
    """When covariates are absent (not returned by _resolve_files), the searcher is still called."""
    fake = make_fake_searcher("local result")
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.LOCAL,
        _make_spec_for(GraphSearchMethodEnum.LOCAL, fake),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        # Only required files; optional files (covariates) deliberately omitted.
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(
        rag_id=1,
        query="local query",
        search_config=GraphLocalSearchConfig(),
    )
    response = await GraphSearchOrchestrator(uow).on_execute(request)

    assert response.result == "local result"
    assert len(fake.calls) == 1
    # covariates is absent from the call kwargs when the fake didn't produce it
    assert "covariates" not in fake.calls[0]


async def test_unsupported_method_raises_unsupported_error(uow, monkeypatch):
    """A search_config.method not in _SEARCH_MAP raises UnsupportedError."""

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    # Use a monkeypatched search_config with a method that isn't in the map.
    # We create a GraphBasicSearchConfig and then override the method field via a
    # simple namespace object so we don't have to fight Pydantic's Literal validation.
    class FakeSearchConfig:
        method = "nonexistent_method"

        def model_dump(self):
            return {}

    class FakeRequest:
        rag_id = 1
        query = "q"
        search_config = FakeSearchConfig()

    with pytest.raises(UnsupportedError):
        await GraphSearchOrchestrator(uow).on_execute(FakeRequest())


async def test_result_propagation_string(uow, monkeypatch):
    """A string result from the searcher is surfaced directly in SearchResult.result."""
    fake = make_fake_searcher("Plain text answer.")
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.BASIC,
        _make_spec_for(GraphSearchMethodEnum.BASIC, fake),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(rag_id=1, query="q", search_config=GraphBasicSearchConfig())
    response = await GraphSearchOrchestrator(uow).on_execute(request)

    assert isinstance(response.result, str)
    assert response.result == "Plain text answer."


async def test_result_propagation_structured(uow, monkeypatch):
    """A list result from the searcher (e.g. list of chunks) is surfaced in SearchResult.result."""
    from domain.models import FoundChunk

    chunks = [
        FoundChunk(order=0, similarity=0.9, text="chunk A", source="doc-1"),
        FoundChunk(order=1, similarity=0.8, text="chunk B", source="doc-2"),
    ]
    fake = make_fake_searcher(chunks)
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.BASIC,
        _make_spec_for(GraphSearchMethodEnum.BASIC, fake),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(rag_id=1, query="q", search_config=GraphBasicSearchConfig())
    response = await GraphSearchOrchestrator(uow).on_execute(request)

    assert response.result == chunks


async def test_get_config_called_with_correct_rag_id(repo, uow, monkeypatch):
    """get_config is called exactly once with the request's rag_id."""
    fake = make_fake_searcher("result")
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.GLOBAL,
        _make_spec_for(GraphSearchMethodEnum.GLOBAL, fake),
    )

    async def fake_resolve_files(config, required_files, optional_files=None):
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(GraphSearchOrchestrator, "_resolve_files", staticmethod(fake_resolve_files))

    request = SearchRequest(rag_id=77, query="q", search_config=GraphGlobalSearchConfig())
    await GraphSearchOrchestrator(uow).on_execute(request)

    assert repo.get_config_calls == [77]


async def test_resolve_files_called_with_correct_parameters(uow, monkeypatch):
    """_resolve_files is invoked with the spec's required_files and optional_files."""
    fake = make_fake_searcher("result")
    monkeypatch.setitem(
        GraphSearchOrchestrator._SEARCH_MAP,
        GraphSearchMethodEnum.LOCAL,
        _make_spec_for(GraphSearchMethodEnum.LOCAL, fake),
    )

    resolve_calls = []

    async def recording_resolve_files(config, required_files, optional_files=None):
        resolve_calls.append(
            {"required_files": list(required_files), "optional_files": list(optional_files or [])}
        )
        return {n: pandas.DataFrame() for n in required_files}

    monkeypatch.setattr(
        GraphSearchOrchestrator, "_resolve_files", staticmethod(recording_resolve_files)
    )

    request = SearchRequest(rag_id=1, query="q", search_config=GraphLocalSearchConfig())
    await GraphSearchOrchestrator(uow).on_execute(request)

    assert len(resolve_calls) == 1
    call = resolve_calls[0]
    expected_required = set(
        GraphSearchOrchestrator._SEARCH_MAP[GraphSearchMethodEnum.LOCAL].required_files
    )
    assert set(call["required_files"]) == expected_required
    # LOCAL has covariates as optional_files
    assert "covariates" in call["optional_files"]
