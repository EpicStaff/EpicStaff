import asyncio
import types
from typing import Literal

import pandas
import pytest
from application.commands import RunIndex
from application.orchestrators.indexing.strategies import graph_indexer
from application.orchestrators.indexing.strategies.graph_indexer import GraphIndexOrchestrator
from domain.enums import DocumentStatusEnum, IndexStatusEnum, SlotEnum
from domain.errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from domain.models import EmbeddingConfig, GraphPricingConfig, Rag
from domain.usage import IndexingRunUsage
from graphrag_input import TextDocument


def _result(workflow: str, error: BaseException | None = None) -> types.SimpleNamespace:
    """Minimal stand-in for PipelineRunResult — only .workflow and .error are used."""
    return types.SimpleNamespace(workflow=workflow, error=error)


def _new_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.NEW, indexing_document_ids=set())


def _make_config(
    *,
    input_storage=None,
    output_storage=None,
    update_output_storage=None,
    vector_store=None,
) -> types.SimpleNamespace:
    """Build a fake GraphRagConfig-like object accepted by _get_config_under_uow."""
    embedding_model = types.SimpleNamespace(api_key=None)
    completion_model = types.SimpleNamespace(api_key=None, type="litellm")
    return types.SimpleNamespace(
        input_storage=input_storage,
        output_storage=output_storage,
        update_output_storage=update_output_storage,
        vector_store=vector_store,
        embedding_models={"default_embedding_model": embedding_model},
        completion_models={"default_completion_model": completion_model},
    )


def _completed_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.COMPLETED, indexing_document_ids=set())


def _text_document(doc_id: int, *, status: str = "new", text: str = "hello world") -> TextDocument:
    """Construct a real TextDocument as the repository does, with a controllable status field."""
    return TextDocument(
        id=str(doc_id),
        text=text,
        title=f"doc_{doc_id}.txt",
        creation_date="2024-01-01T00:00:00",
        raw_data={"status": status},
    )


def _make_request(document_ids: frozenset[int], rag_id: int = 1) -> RunIndex:
    return RunIndex(
        rag_id=rag_id,
        document_ids=document_ids,
        embedding_api_key="sk-test",
        llm_api_key="sk-llm",
    )


_PRICING = GraphPricingConfig(
    embedding=EmbeddingConfig(provider="openai", model="text-embedding-3-small"),
    llm_provider="openai",
    llm_model="gpt-4o-mini",
)


class FakeGraphRagRepo:
    """In-memory repo for the GraphIndexer flow."""

    def __init__(
        self,
        *,
        rag: Rag | None,
        config: object | None,
        documents: list[TextDocument],
        has_indexed_db: bool = False,
        other_document_statuses: dict[int, str] | None = None,
        get_rag_raises: BaseException | None = None,
        get_documents_raises: BaseException | None = None,
        pricing: GraphPricingConfig | None = None,
    ):
        self._pricing = pricing or _PRICING
        self.usage_runs: list[IndexingRunUsage] = []
        self._rag = rag
        self._config = config
        self._documents = documents
        self._has_indexed_db = has_indexed_db
        self._get_rag_raises = get_rag_raises
        self._get_documents_raises = get_documents_raises

        self.rag_status_log: list[IndexStatusEnum] = []
        self.rag_slot_log: list[SlotEnum | None] = []
        self.status_updates: list[tuple[frozenset[int], str]] = []
        self.build_index_call_count: int = 0
        self._document_statuses: dict[int, str] = dict(other_document_statuses or {})
        self.get_config_calls: list[tuple[int, SlotEnum | None]] = []

    async def get_rag(self, rag_id: int) -> Rag | None:
        if self._get_rag_raises is not None:
            raise self._get_rag_raises
        return self._rag

    async def get_pricing_config(self, rag_id: int) -> GraphPricingConfig:
        return self._pricing

    async def add_indexing_usage(self, rag_id: int, run: IndexingRunUsage) -> None:
        self.usage_runs.append(run)

    async def get_config(self, rag_id: int, slot: SlotEnum | None = None) -> object | None:
        self.get_config_calls.append((rag_id, slot))
        return self._config

    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[TextDocument]:
        if self._get_documents_raises is not None:
            raise self._get_documents_raises
        return [d for d in self._documents if int(d.id) in ids]

    async def has_indexed_document(self, rag_id: int) -> bool:
        return self._has_indexed_db

    async def get_indexed_documents_excluding(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        return [d for d in self._documents if int(d.id) not in ids]

    async def update_rag(self, rag: Rag) -> None:
        if not self.rag_status_log or self.rag_status_log[-1] != rag.status:
            self.rag_status_log.append(rag.status)
        self.rag_slot_log.append(rag.slot)

    async def update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: Literal["new", "completed", "failed"],
    ) -> None:
        self.status_updates.append((frozenset(ids), status))
        for doc_id in ids:
            self._document_statuses[doc_id] = status

    async def has_completed_document(self, rag_id: int) -> bool:
        return any(s == DocumentStatusEnum.COMPLETED for s in self._document_statuses.values())

    async def has_failed_document(self, rag_id: int) -> bool:
        return any(s == DocumentStatusEnum.FAILED for s in self._document_statuses.values())

    async def has_outdated_document(self, rag_id: int) -> bool:
        return any(s == DocumentStatusEnum.OUTDATED for s in self._document_statuses.values())


class FakeUoW:
    """In-memory unit of work — re-enterable (GraphIndexer opens it many times)."""

    def __init__(self, repo: FakeGraphRagRepo):
        self.graph_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        pass


async def test_index_builds_the_graph_from_the_documents_and_completes_the_rag(monkeypatch):
    rag = _new_rag()
    doc_a = _text_document(1, text="first document text")
    doc_b = _text_document(2, text="second document text")
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[doc_a, doc_b])
    uow = FakeUoW(repo)

    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({1, 2}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert captured["config"] is config
    assert config.embedding_models["default_embedding_model"].api_key == "sk-test"
    assert config.completion_models["default_completion_model"].api_key == "sk-llm"
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert repo.status_updates == [(frozenset({1, 2}), DocumentStatusEnum.COMPLETED)]
    assert rag.indexing_document_ids == set()

    df: pandas.DataFrame = captured["input_documents"]
    assert isinstance(df, pandas.DataFrame)
    assert len(df) == 2
    row_ids = set(df["id"].tolist())
    assert row_ids == {"1", "2"}
    row_texts = set(df["text"].tolist())
    assert row_texts == {"first document text", "second document text"}


@pytest.mark.parametrize(
    "rag_completed, request_has_completed_doc, expected_is_update_run",
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    ],
    ids=[
        "rag_completed_request_new_docs_expect_update",
        "rag_completed_request_has_completed_doc_expect_no_update",
        "rag_new_request_new_docs_expect_no_update",
        "rag_new_request_has_completed_doc_expect_no_update",
    ],
)
async def test_is_update_run_computed_correctly(
    monkeypatch,
    rag_completed: bool,
    request_has_completed_doc: bool,
    expected_is_update_run: bool,
):
    rag = _completed_rag() if rag_completed else _new_rag()
    rag.slot = SlotEnum.A
    doc_status = "completed" if request_has_completed_doc else "new"
    document = _text_document(10, status=doc_status)
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)
    _make_slot_monkeypatches(monkeypatch)

    captured_is_update_run: list[bool] = []

    async def fake_build_index(**kwargs):
        captured_is_update_run.append(kwargs["is_update_run"])
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({10}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert captured_is_update_run == [expected_is_update_run]


async def test_indexing_errors_raise_exception_group_and_mark_rag_failed(monkeypatch):
    rag = _new_rag()
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    async def fake_build_index(**kwargs):
        return [
            _result("extract_graph", ValueError("boom")),
            _result("cluster_graph"),  # success — only the error one matters
        ]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))

    with pytest.raises(ExceptionGroup):
        await GraphIndexOrchestrator(uow).execute(request)

    assert repo.status_updates == [(frozenset({7}), DocumentStatusEnum.FAILED)]
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.FAILED]


async def test_missing_rag_raises_and_marks_nothing(monkeypatch):
    repo = FakeGraphRagRepo(rag=None, config=object(), documents=[])
    uow = FakeUoW(repo)

    build_index_called = []

    async def fake_build_index(**kwargs):
        build_index_called.append(True)
        return []

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({1}))

    with pytest.raises(RagNotFoundError):
        await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == []
    assert build_index_called == []


async def test_missing_config_marks_rag_failed_and_reraises(monkeypatch):
    rag = _new_rag()
    document = _text_document(5)
    repo = FakeGraphRagRepo(rag=rag, config=None, documents=[document])
    uow = FakeUoW(repo)

    build_index_called = []

    async def fake_build_index(**kwargs):
        build_index_called.append(True)
        return []

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({5}))

    with pytest.raises(GraphRagConfigNotFoundError):
        await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.FAILED]
    assert build_index_called == []
    assert repo.status_updates == []


async def test_no_documents_marks_rag_failed_and_reraises(monkeypatch):
    rag = _new_rag()
    repo = FakeGraphRagRepo(rag=rag, config=object(), documents=[])
    uow = FakeUoW(repo)

    build_index_called = []

    async def fake_build_index(**kwargs):
        build_index_called.append(True)
        return []

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)
    request = _make_request(frozenset({99}))

    with pytest.raises(DocumentNotFoundError):
        await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.FAILED]
    assert build_index_called == []


async def test_cancellation_while_building_marks_rag_cancelled(monkeypatch):
    rag = _new_rag()
    repo = FakeGraphRagRepo(rag=rag, config=_make_config(), documents=[_text_document(7)])

    async def cancelled_build_index(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(graph_indexer, "build_index", cancelled_build_index)

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED]
    assert repo.status_updates == []
    assert rag.indexing_document_ids == set()


async def test_graph_rag_never_resolves_to_partial_when_failed_doc_exists(monkeypatch):
    rag = _new_rag()
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(
        rag=rag,
        config=config,
        documents=[document],
        other_document_statuses={99: DocumentStatusEnum.FAILED},
    )
    uow = FakeUoW(repo)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)
    assert rag.status == IndexStatusEnum.COMPLETED
    assert IndexStatusEnum.PARTIAL not in repo.rag_status_log


async def test_outdated_doc_keeps_rag_outdated_and_preserves_reasons(monkeypatch):
    rag = _new_rag()
    rag.outdated_reasons = {"doc_99": "source_changed"}
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(
        rag=rag,
        config=config,
        documents=[document],
        other_document_statuses={99: DocumentStatusEnum.OUTDATED},
    )
    uow = FakeUoW(repo)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert rag.status == IndexStatusEnum.OUTDATED
    assert rag.outdated_reasons == {"doc_99": "source_changed"}


async def test_outdated_reasons_cleared_when_no_outdated_document_remains(monkeypatch):
    rag = _new_rag()
    rag.outdated_reasons = {"x": "y"}
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert rag.outdated_reasons == {}
    assert rag.status == IndexStatusEnum.COMPLETED


def _make_slot_monkeypatches(monkeypatch) -> list[str]:
    """Replace graphrag's S3 storage; returns the prefixes of every storage cleared."""
    cleared_prefixes: list[str] = []

    class FakeStorage:
        def __init__(self, config):
            self.prefix = config.prefix

        async def clear(self):
            cleared_prefixes.append(self.prefix)

    monkeypatch.setattr(graph_indexer, "create_storage", FakeStorage)
    return cleared_prefixes


def _make_full_reindex_setup(*, rag_slot: SlotEnum = SlotEnum.A):
    """
    Return (rag, config, repo, uow, request) for a full-reindex scenario:
    - rag is COMPLETED with rag.slot = rag_slot
    - request contains a single doc (id=10) whose status is 'completed'
    This combination triggers the full-reindex branch in on_execute.

    The config is a sentinel that the fake repo returns; the orchestrator no longer
    mutates it — instead it requests a fresh config for the target slot via get_config.
    """
    rag = _completed_rag(rag_id=1)
    rag.slot = rag_slot
    config = _make_config()
    completed_doc = _text_document(10, status="completed")
    extra_doc = _text_document(20, status="new")
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[completed_doc, extra_doc])
    uow = FakeUoW(repo)
    request = _make_request(frozenset({10}))

    return rag, config, repo, uow, request


@pytest.mark.parametrize(
    ("current_slot", "target_slot"),
    [(SlotEnum.A, SlotEnum.B), (SlotEnum.B, SlotEnum.A)],
    ids=["a-to-b", "b-to-a"],
)
async def test_full_reindex_builds_into_the_other_slot_then_switches_and_clears_the_old_one(
    monkeypatch, current_slot, target_slot
):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=current_slot)
    cleared_prefixes = _make_slot_monkeypatches(monkeypatch)
    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)

    assert repo.get_config_calls == [(rag.id, target_slot)]
    assert captured["config"] is config
    assert captured["is_update_run"] is False
    # Already-indexed documents outside the request are rebuilt into the new slot too.
    assert set(captured["input_documents"]["id"]) == {"10", "20"}
    assert rag.slot == target_slot
    assert repo.rag_slot_log[-1] == target_slot
    assert cleared_prefixes == [f"graphrag/rag_1/{current_slot}"]


async def test_full_reindex_cancelled_clears_target_and_keeps_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    cleared_prefixes = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)
    assert rag.slot == SlotEnum.A
    assert rag.status == IndexStatusEnum.CANCELLED
    assert cleared_prefixes == ["graphrag/rag_1/b"]


async def test_full_reindex_error_clears_target_and_keeps_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    cleared_prefixes = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph", ValueError("boom"))]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    with pytest.raises(ExceptionGroup):
        await GraphIndexOrchestrator(uow).execute(request)

    assert rag.slot == SlotEnum.A
    assert rag.status == IndexStatusEnum.FAILED
    assert any(
        ids == frozenset({10}) and status == DocumentStatusEnum.FAILED
        for ids, status in repo.status_updates
    )
    assert cleared_prefixes == ["graphrag/rag_1/b"]


async def test_first_index_touches_no_slot_storage(monkeypatch):
    rag = _new_rag()  # status=NEW, slot=None
    document = _text_document(5, status="new")
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    cleared_prefixes = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)
    await GraphIndexOrchestrator(uow).execute(_make_request(frozenset({5})))
    assert rag.slot is None
    assert cleared_prefixes == []


async def test_extra_headers_injected_into_both_graphrag_models(monkeypatch):
    config = _make_config()
    config.embedding_models["default_embedding_model"].call_args = {}
    config.completion_models["default_completion_model"].call_args = {"temperature": 0.1}
    repo = FakeGraphRagRepo(rag=_new_rag(), config=config, documents=[_text_document(7)])
    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = RunIndex(
        rag_id=1,
        document_ids=frozenset({7}),
        embedding_api_key="sk-test",
        llm_api_key="sk-llm",
        embedding_extra_headers={"X-Emb": "emb-resolved"},
        llm_extra_headers={"X-Llm": "llm-resolved"},
    )
    await GraphIndexOrchestrator(FakeUoW(repo)).execute(request)

    sent = captured["config"]
    assert sent.embedding_models["default_embedding_model"].call_args == {
        "extra_headers": {"X-Emb": "emb-resolved"}
    }
    assert sent.completion_models["default_completion_model"].call_args == {
        "temperature": 0.1,
        "extra_headers": {"X-Llm": "llm-resolved"},
    }


def _metered_config() -> types.SimpleNamespace:
    """A config whose models are real graphrag_llm models answering from litellm's mock."""
    from graphrag_llm.config import ModelConfig

    return types.SimpleNamespace(
        input_storage=None,
        output_storage=None,
        update_output_storage=None,
        vector_store=None,
        embedding_models={
            "default_embedding_model": ModelConfig(
                model_provider="openai",
                model="text-embedding-3-small",
                api_key="x",
                call_args={"mock_response": [0.1, 0.2]},
            )
        },
        completion_models={
            "default_completion_model": ModelConfig(
                model_provider="openai",
                model="gpt-4o-mini",
                api_key="x",
                call_args={"mock_response": "an answer"},
            )
        },
    )


def _calling_build_index(*, embeddings: int, completions: int, error: BaseException | None = None):
    """A `build_index` stand-in that makes real graphrag_llm calls through `config`."""
    from graphrag_llm.completion import create_completion
    from graphrag_llm.embedding import create_embedding

    async def build_index(*, config, **_):
        completion = create_completion(config.completion_models["default_completion_model"])
        embedding = create_embedding(config.embedding_models["default_embedding_model"])
        for _ in range(completions):
            await completion.completion_async(messages="say something")
        for _ in range(embeddings):
            await embedding.embedding_async(input=["some text"])
        if error is not None:
            raise error
        return [_result("workflow_a")]

    return build_index


async def test_run_records_usage_reported_by_graphrag_models(monkeypatch):
    repo = FakeGraphRagRepo(rag=_new_rag(), config=_metered_config(), documents=[_text_document(7)])
    monkeypatch.setattr(
        graph_indexer, "build_index", _calling_build_index(embeddings=2, completions=3)
    )

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    (run,) = repo.usage_runs
    assert run.embedding_tokens > 0
    assert run.llm_input_tokens > 0
    assert run.llm_output_tokens > 0
    assert run.cost_usd is not None


async def test_run_prefers_custom_llm_prices_over_the_price_map(monkeypatch):
    pricing = _PRICING.model_copy(
        update={"input_cost_per_token": 1.0, "output_cost_per_token": 2.0}
    )
    repo = FakeGraphRagRepo(
        rag=_new_rag(), config=_metered_config(), documents=[_text_document(7)], pricing=pricing
    )
    monkeypatch.setattr(
        graph_indexer, "build_index", _calling_build_index(embeddings=1, completions=1)
    )
    monkeypatch.setattr(graph_indexer, "embedding_cost", lambda model, tokens: 0.0)

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    (run,) = repo.usage_runs
    assert run.cost_usd == run.llm_input_tokens * 1.0 + run.llm_output_tokens * 2.0


async def test_run_records_null_cost_when_the_llm_is_unpriced(monkeypatch):
    pricing = _PRICING.model_copy(update={"llm_model": "no-such-llm"})
    repo = FakeGraphRagRepo(
        rag=_new_rag(), config=_metered_config(), documents=[_text_document(7)], pricing=pricing
    )
    monkeypatch.setattr(
        graph_indexer, "build_index", _calling_build_index(embeddings=1, completions=1)
    )

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    (run,) = repo.usage_runs
    assert run.llm_input_tokens > 0
    assert run.cost_usd is None


async def test_failed_run_records_usage_consumed_before_the_failure(monkeypatch):
    repo = FakeGraphRagRepo(rag=_new_rag(), config=_metered_config(), documents=[_text_document(7)])
    monkeypatch.setattr(
        graph_indexer,
        "build_index",
        _calling_build_index(embeddings=1, completions=2, error=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    (run,) = repo.usage_runs
    assert run.llm_input_tokens > 0
    assert repo.rag_status_log[-1] == IndexStatusEnum.FAILED


async def test_concurrent_runs_keep_their_usage_apart(monkeypatch):
    first = FakeGraphRagRepo(rag=_new_rag(1), config=_metered_config(), documents=[_text_document(7)])
    second = FakeGraphRagRepo(rag=_new_rag(2), config=_metered_config(), documents=[_text_document(8)])
    calls_by_document_id = {"7": 1, "8": 4}

    async def build_index(*, config, **kwargs):
        rag_calls = calls_by_document_id[kwargs["input_documents"].iloc[0]["id"]]
        return await _calling_build_index(embeddings=0, completions=rag_calls)(config=config)

    monkeypatch.setattr(graph_indexer, "build_index", build_index)

    await asyncio.gather(
        GraphIndexOrchestrator(FakeUoW(first)).execute(_make_request(frozenset({7}), rag_id=1)),
        GraphIndexOrchestrator(FakeUoW(second)).execute(_make_request(frozenset({8}), rag_id=2)),
    )

    assert second.usage_runs[0].llm_input_tokens == 4 * first.usage_runs[0].llm_input_tokens


async def test_missing_pricing_config_leaves_cost_null_and_does_not_fail_the_run(monkeypatch):
    repo = FakeGraphRagRepo(rag=_new_rag(), config=_metered_config(), documents=[_text_document(7)])

    async def no_pricing(rag_id: int):
        return None

    monkeypatch.setattr(repo, "get_pricing_config", no_pricing)
    monkeypatch.setattr(
        graph_indexer, "build_index", _calling_build_index(embeddings=1, completions=1)
    )

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    (run,) = repo.usage_runs
    assert run.llm_input_tokens > 0
    assert run.cost_usd is None
    assert repo.rag_status_log[-1] == IndexStatusEnum.COMPLETED


async def test_run_without_model_calls_records_no_usage(monkeypatch):
    repo = FakeGraphRagRepo(rag=_new_rag(), config=_make_config(), documents=[_text_document(7)])

    async def fake_build_index(**kwargs):
        return [_result("workflow_a")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(FakeUoW(repo)).execute(_make_request(frozenset({7})))

    assert repo.usage_runs == []


async def test_build_index_never_enables_graphrag_verbose_logging(monkeypatch):
    rag = _new_rag()
    doc = _text_document(1, text="test")
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[doc])
    uow = FakeUoW(repo)

    captured = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({1}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert captured.get("verbose", False) is False
