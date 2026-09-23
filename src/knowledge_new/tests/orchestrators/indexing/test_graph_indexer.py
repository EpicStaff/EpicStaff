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
from domain.models import Rag
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
    completion_model = types.SimpleNamespace(api_key=None)
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


class FakeGraphRagRepo:
    """In-memory repo for the GraphIndexer flow."""

    def __init__(
        self,
        *,
        rag: Rag | None,
        config: object | None,
        documents: list[TextDocument],
        has_indexed_db: bool = False,
        get_rag_raises: BaseException | None = None,
        get_documents_raises: BaseException | None = None,
    ):
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
        self._document_statuses: dict[int, str] = {}
        self.get_config_calls: list[tuple[int, SlotEnum | None]] = []

    async def get_rag(self, rag_id: int) -> Rag | None:
        if self._get_rag_raises is not None:
            raise self._get_rag_raises
        return self._rag

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

    def __init__(
        self,
        repo: FakeGraphRagRepo,
        *,
        commit_errors: list[BaseException | None] | None = None,
    ):
        self.graph_rag_repo = repo
        self._commit_errors: list[BaseException | None] = list(commit_errors or [])
        self.commit_count: int = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.commit_count += 1
        if self._commit_errors:
            exc = self._commit_errors.pop(0)
            if exc is not None:
                raise exc


async def test_index_success_full_flow_marks_documents_indexed_and_rag_completed(monkeypatch):
    rag = _new_rag()
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    build_index_called = []

    async def fake_build_index(**kwargs):
        build_index_called.append(kwargs)
        return [_result("workflow_a"), _result("workflow_b")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert repo.status_updates == [(frozenset({7}), DocumentStatusEnum.COMPLETED)]
    assert rag.indexing_document_ids == set()
    assert len(build_index_called) == 1


async def test_build_index_receives_documents_dataframe_and_config(monkeypatch):
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
    assert captured["verbose"] is True

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
    _make_slot_monkeypatches(monkeypatch)  # noqa: prevent real MinIO calls in _clear_slot_storage

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


@pytest.mark.parametrize(
    "cancel_scenario",
    [
        "during_build_index",
        "during_processing_commit",
    ],
)
async def test_cancellation_marks_rag_cancelled(monkeypatch, cancel_scenario: str):
    rag = _new_rag()
    document = _text_document(7)
    config = _make_config()

    build_index_called = []

    if cancel_scenario == "during_build_index":
        repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
        uow = FakeUoW(repo)

        async def fake_build_index(**kwargs):
            build_index_called.append(True)
            raise asyncio.CancelledError()

        monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    else:
        repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
        uow = FakeUoW(repo, commit_errors=[asyncio.CancelledError(), None])

        async def fake_build_index(**kwargs):
            build_index_called.append(True)
            return []

        monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))

    await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED]
    assert repo.status_updates == []

    if cancel_scenario == "during_build_index":
        assert build_index_called == [True]
    else:
        assert build_index_called == []


async def test_graph_rag_never_resolves_to_partial_when_failed_doc_exists(monkeypatch):
    rag = _new_rag()
    document = _text_document(7)
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    repo._document_statuses[99] = DocumentStatusEnum.FAILED

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
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    repo._document_statuses[99] = DocumentStatusEnum.OUTDATED

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


class _StorageConfigSentinel:
    """Lightweight stand-in returned by the fake create_storage_config."""

    def __init__(self, subdir: str):
        self.subdir = subdir

    def __repr__(self):
        return f"StorageConfigSentinel(subdir={self.subdir!r})"


class _FakeStorage:
    """Fake storage object whose async clear() records that it was called."""

    def __init__(self, config: _StorageConfigSentinel):
        self.config = config
        self.clear_called = False

    async def clear(self):
        self.clear_called = True


def _make_slot_monkeypatches(monkeypatch):
    """
    Patch the two names still imported into graph_indexer so no real MinIO work happens.
    `create_storage_config` is used only by `_clear_slot_storage`; `create_storage` wraps
    it into a fake storage whose `clear()` is tracked.

    `create_vector_store_config` was removed from graph_indexer after the fix — the repo
    now builds the full config through its constructor, so there is nothing to patch here.

    Returns (storage_configs_called, storages_created).
    """
    storage_configs_called: list[_StorageConfigSentinel] = []
    storages_created: list[_FakeStorage] = []

    def fake_create_storage_config(*, rag_id: int, subdir: str) -> _StorageConfigSentinel:
        sentinel = _StorageConfigSentinel(subdir=subdir)
        storage_configs_called.append(sentinel)
        return sentinel

    def fake_create_storage(config: _StorageConfigSentinel) -> _FakeStorage:
        storage = _FakeStorage(config=config)
        storages_created.append(storage)
        return storage

    monkeypatch.setattr(graph_indexer, "create_storage_config", fake_create_storage_config)
    monkeypatch.setattr(graph_indexer, "create_storage", fake_create_storage)

    return storage_configs_called, storages_created


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


async def test_full_reindex_requests_config_for_target_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _make_slot_monkeypatches(monkeypatch)

    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)

    assert len(repo.get_config_calls) == 1
    called_rag_id, called_slot = repo.get_config_calls[0]
    assert called_rag_id == rag.id
    assert called_slot == SlotEnum.B
    assert captured["config"] is config
    assert captured["is_update_run"] is False


async def test_full_reindex_success_promotes_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _make_slot_monkeypatches(monkeypatch)  # prevent real MinIO calls in _clear_slot_storage

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)
    assert rag.slot == SlotEnum.B
    assert repo.rag_slot_log[-1] == SlotEnum.B


@pytest.mark.parametrize(
    "initial_slot, expected_target_slot",
    [
        (SlotEnum.A, SlotEnum.B),
        (SlotEnum.B, SlotEnum.A),
    ],
    ids=["slot_a_targets_b", "slot_b_targets_a"],
)
async def test_target_slot_computation(monkeypatch, initial_slot, expected_target_slot):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=initial_slot)
    _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)

    # get_config must have been called with the target slot.
    assert len(repo.get_config_calls) == 1
    _, called_slot = repo.get_config_calls[0]
    assert called_slot == expected_target_slot


async def test_full_reindex_cancelled_clears_target_and_keeps_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _, storages_created = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)
    assert rag.slot == SlotEnum.A
    assert rag.status == IndexStatusEnum.CANCELLED
    cleared_subdirs = [s.config.subdir for s in storages_created if s.clear_called]
    assert SlotEnum.B in cleared_subdirs


async def test_full_reindex_error_clears_target_and_keeps_slot(monkeypatch):
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _, storages_created = _make_slot_monkeypatches(monkeypatch)

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
    cleared_subdirs = [s.config.subdir for s in storages_created if s.clear_called]
    assert SlotEnum.B in cleared_subdirs


async def test_normal_index_no_slot_ops_no_keyerror(monkeypatch):
    rag = _new_rag()  # status=NEW, slot=None
    document = _text_document(5, status="new")
    config = _make_config()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    _, storages_created = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)
    await GraphIndexOrchestrator(uow).execute(_make_request(frozenset({5})))
    assert rag.slot is None
    assert not any(s.clear_called for s in storages_created)
