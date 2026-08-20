import asyncio
import types
from typing import Literal

import pandas
import pytest
from application.orchestrators.indexing.strategies import graph_indexer
from application.orchestrators.indexing.strategies.graph_indexer import GraphIndexOrchestrator
from domain.enums import DocumentStatusEnum, IndexStatusEnum, RAGStrategy, SlotEnum
from domain.errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from domain.models import IndexRequest, Rag
from graphrag_input import TextDocument


def _result(workflow: str, error: BaseException | None = None) -> types.SimpleNamespace:
    """Minimal stand-in for PipelineRunResult — only .workflow and .error are used."""
    return types.SimpleNamespace(workflow=workflow, error=error)


def _new_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.NEW, indexing_document_ids=set())


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


def _make_request(document_ids: frozenset[int], rag_id: int = 1) -> IndexRequest:
    return IndexRequest(
        rag_id=rag_id,
        rag_strategy=RAGStrategy.GRAPH,
        document_ids=document_ids,
    )


class FakeGraphRagRepo:
    """In-memory repo for the GraphIndexer flow.

    rag_status_log appends only when rag.status actually changes — _update_rag is
    called on every persist (PROCESSING, CANCELLED, FAILED, COMPLETED), and the
    on_cancel/on_error paths each call it once too. Logging every call without
    de-duplication would fill the log with identical entries when statuses repeat.

    status_updates records (frozenset(ids), status) for each update_status_of_documents call.

    get_rag_raises / get_documents_raises inject a failure at the preparation stage,
    mimicking transient repo errors or intentional test scenarios (e.g. missing RAG).

    get_config_calls records the (rag_id, slot) kwargs for each get_config invocation so
    tests can verify the correct slot is requested.
    """

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
        # Append only when status actually changes to avoid duplicate log entries.
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
    """In-memory unit of work — re-enterable (GraphIndexer opens it many times).

    commit_errors is consumed one entry per commit() call: a non-None entry is raised,
    letting a test inject a failure at a specific persistence step without touching
    production code. None entries are no-ops (successful commits).
    """

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
    config = object()
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
    config = object()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[doc_a, doc_b])
    uow = FakeUoW(repo)

    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({1, 2}))
    await GraphIndexOrchestrator(uow).execute(request)

    # config object must be forwarded by identity, not copied
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
    # is_update_run is True only when rag.status==COMPLETED AND none of the request
    # documents has raw_data['status']=='completed'. The repo.has_indexed_document flag
    # is not consulted by production code for this decision.
    rag = _completed_rag() if rag_completed else _new_rag()
    rag.slot = SlotEnum.A
    doc_status = "completed" if request_has_completed_doc else "new"
    document = _text_document(10, status=doc_status)
    config = types.SimpleNamespace(
        input_storage=None,
        output_storage=None,
        update_output_storage=None,
        vector_store=None,
    )
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
    config = object()
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

    # documents are marked FAILED when indexing errors occurred
    assert repo.status_updates == [(frozenset({7}), DocumentStatusEnum.FAILED)]
    # on_error ran after the ExceptionGroup was raised inside on_execute
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.FAILED]


async def test_missing_rag_raises_and_marks_nothing(monkeypatch):
    # rag=None → _get_rag_under_uow raises RagNotFoundError; self.state['rag'] is never set
    # → on_error has nothing to mark (no-op)
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
    # config=None → _get_config_under_uow raises GraphRagConfigNotFoundError.
    # rag was already fetched and stored in self.state["rag"] → on_error marks FAILED.
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
    # get_documents returns [] → _get_documents_under_uow raises DocumentNotFoundError.
    # rag was fetched → on_error marks FAILED.
    rag = _new_rag()
    repo = FakeGraphRagRepo(rag=rag, config=object(), documents=[])
    uow = FakeUoW(repo)

    build_index_called = []

    async def fake_build_index(**kwargs):
        build_index_called.append(True)
        return []

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    # document_ids references a doc that the repo won't return (empty documents list)
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
    config = object()

    build_index_called = []

    if cancel_scenario == "during_build_index":
        # build_index raises CancelledError mid-indexing; rag is already PROCESSING
        repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
        uow = FakeUoW(repo)

        async def fake_build_index(**kwargs):
            build_index_called.append(True)
            raise asyncio.CancelledError()

        monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    else:
        # during_processing_commit: the first commit (persisting PROCESSING) raises
        # CancelledError after update_rag already appended PROCESSING to rag_status_log.
        # on_cancel then calls _update_rag again using the second commit (None = success).
        repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
        uow = FakeUoW(repo, commit_errors=[asyncio.CancelledError(), None])

        async def fake_build_index(**kwargs):
            build_index_called.append(True)
            return []

        monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))

    # execute() swallows CancelledError (the base only re-raises RepositoryError / generic
    # Exception; the cancellation path calls on_cancel and does NOT re-raise).
    await GraphIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED]
    assert repo.status_updates == []

    if cancel_scenario == "during_build_index":
        assert build_index_called == [True]
    else:
        # build_index never reached because commit raised before that point
        assert build_index_called == []


async def test_graph_rag_never_resolves_to_partial_when_failed_doc_exists(monkeypatch):
    """Regression guard: GraphRag has no PARTIAL status.

    A pre-existing FAILED document combined with a newly COMPLETED document must
    resolve to COMPLETED, not PARTIAL.  PARTIAL must never appear in rag_status_log.
    """
    rag = _new_rag()
    document = _text_document(7)
    config = object()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    # Simulate a doc from a prior run that is already FAILED in the repository.
    repo._document_statuses[99] = DocumentStatusEnum.FAILED

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    # After the run: doc 7 → COMPLETED, doc 99 → FAILED (pre-existing).
    # _finish_rag priority: OUTDATED > PROCESSING > COMPLETED > FAILED.
    # has_completed is True (doc 7), so the rag resolves to COMPLETED.
    assert rag.status == IndexStatusEnum.COMPLETED
    assert IndexStatusEnum.PARTIAL not in repo.rag_status_log


async def test_outdated_doc_keeps_rag_outdated_and_preserves_reasons(monkeypatch):
    """When a document outside the current request has OUTDATED status, the rag is
    marked OUTDATED and outdated_reasons are preserved unchanged."""
    rag = _new_rag()
    rag.outdated_reasons = {"doc_99": "source_changed"}
    document = _text_document(7)
    config = object()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    # Simulate a pre-existing OUTDATED doc (outside the current request).
    repo._document_statuses[99] = DocumentStatusEnum.OUTDATED

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    # has_outdated is True → rag must be OUTDATED with reasons intact.
    assert rag.status == IndexStatusEnum.OUTDATED
    assert rag.outdated_reasons == {"doc_99": "source_changed"}


async def test_outdated_reasons_cleared_when_no_outdated_document_remains(monkeypatch):
    """When no document has OUTDATED status after a run, outdated_reasons is cleared."""
    rag = _new_rag()
    rag.outdated_reasons = {"x": "y"}
    document = _text_document(7)
    config = object()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    # No OUTDATED docs seeded — only doc 7 will be COMPLETED after the run.

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({7}))
    await GraphIndexOrchestrator(uow).execute(request)

    # No OUTDATED doc remains → reasons cleared → rag is COMPLETED (not OUTDATED).
    assert rag.outdated_reasons == {}
    assert rag.status == IndexStatusEnum.COMPLETED


# ---------------------------------------------------------------------------
# Slot-focused tests
# ---------------------------------------------------------------------------

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

    config = types.SimpleNamespace(
        input_storage=None,
        output_storage=None,
        update_output_storage=None,
        vector_store=None,
    )

    # doc 10 has status='completed' → _has_indexed_document returns True → full-reindex branch.
    completed_doc = _text_document(10, status="completed")
    # An extra doc (id=20) with status='new' is in the repo so that
    # get_indexed_documents_excluding (returning docs NOT in {10}) returns it.
    extra_doc = _text_document(20, status="new")

    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[completed_doc, extra_doc])
    uow = FakeUoW(repo)
    request = _make_request(frozenset({10}))

    return rag, config, repo, uow, request


async def test_full_reindex_requests_config_for_target_slot(monkeypatch):
    """
    Full-reindex branch: when rag.slot=A and the request contains a completed doc,
    get_config must be called with slot=SlotEnum.B so that a fresh GraphRagConfig is
    built through the constructor (ensuring vector_store.index_schema is populated).
    The config returned by the repo is forwarded unchanged to build_index, and
    is_update_run must be False.
    """
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _make_slot_monkeypatches(monkeypatch)

    captured: dict = {}

    async def fake_build_index(**kwargs):
        captured.update(kwargs)
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)

    # get_config must have been called with the target slot (B), not the active slot (A).
    assert len(repo.get_config_calls) == 1
    called_rag_id, called_slot = repo.get_config_calls[0]
    assert called_rag_id == rag.id
    assert called_slot == SlotEnum.B

    # config identity: build_index received the exact object the repo returned.
    assert captured["config"] is config

    # Full-reindex → is_update_run must be False.
    assert captured["is_update_run"] is False


async def test_full_reindex_success_promotes_slot(monkeypatch):
    """
    After a successful full-reindex, rag.slot must be promoted to the target slot (B),
    and update_rag must have been called with a rag whose slot is B.

    NOTE: The production _finish_rag also clears the OLD slot's storage after promoting.
    This test asserts the cutover only; it does not assert the absence of clear() calls
    because clear() IS called on the old slot (production behaviour).
    """
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _make_slot_monkeypatches(monkeypatch)  # prevent real MinIO calls in _clear_slot_storage

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    await GraphIndexOrchestrator(uow).execute(request)

    # Slot must have been promoted to B on the rag object.
    assert rag.slot == SlotEnum.B

    # The final update_rag call (from _finish_rag) must persist a rag with slot B.
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
    """
    Target slot is always the opposite of the current rag.slot:
    A → B, B → A.  Verified via the slot passed to get_config.
    """
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
    """
    When a full-reindex is cancelled (CancelledError from build_index):
    - on_cancel must call _clear_slot_storage on the TARGET slot (B).
    - rag.slot must remain unchanged (A — not promoted).
    - rag.status must be CANCELLED.
    """
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _, storages_created = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    # execute() swallows CancelledError and runs on_cancel.
    await GraphIndexOrchestrator(uow).execute(request)

    # Slot must NOT have been promoted.
    assert rag.slot == SlotEnum.A

    # rag.status must be CANCELLED.
    assert rag.status == IndexStatusEnum.CANCELLED

    # _clear_slot_storage (called from on_cancel) creates a storage for the target slot
    # and calls clear() on it.  The subdir in _clear_slot_storage is just the slot value.
    cleared_subdirs = [s.config.subdir for s in storages_created if s.clear_called]
    assert SlotEnum.B in cleared_subdirs


async def test_full_reindex_error_clears_target_and_keeps_slot(monkeypatch):
    """
    When a full-reindex fails (build_index returns a result with an error):
    - An ExceptionGroup is raised.
    - on_error must call _clear_slot_storage on the TARGET slot (B).
    - rag.slot must remain unchanged (A — not promoted).
    - rag.status must be FAILED.
    - The request documents must be marked FAILED.
    """
    rag, config, repo, uow, request = _make_full_reindex_setup(rag_slot=SlotEnum.A)
    _, storages_created = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph", ValueError("boom"))]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    with pytest.raises(ExceptionGroup):
        await GraphIndexOrchestrator(uow).execute(request)

    # Slot must NOT have been promoted.
    assert rag.slot == SlotEnum.A

    # rag.status must be FAILED.
    assert rag.status == IndexStatusEnum.FAILED

    # Documents in the request must be marked FAILED.
    assert any(
        ids == frozenset({10}) and status == DocumentStatusEnum.FAILED
        for ids, status in repo.status_updates
    )

    # _clear_slot_storage (called from on_error) must have cleared the target slot (B).
    cleared_subdirs = [s.config.subdir for s in storages_created if s.clear_called]
    assert SlotEnum.B in cleared_subdirs


async def test_normal_index_no_slot_ops_no_keyerror(monkeypatch):
    """
    Regression guard: when a NEW rag runs with fresh (non-completed) documents, the
    full-reindex branch is NOT triggered. _finish_rag must NOT raise a KeyError when
    self.state['target_slot'] is absent (the .get() guard). No clear() must be called.
    rag.slot stays at its initial value (None for a new rag).
    """
    rag = _new_rag()  # status=NEW, slot=None
    document = _text_document(5, status="new")
    config = types.SimpleNamespace(
        input_storage=None,
        output_storage=None,
        update_output_storage=None,
        vector_store=None,
    )
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

    _, storages_created = _make_slot_monkeypatches(monkeypatch)

    async def fake_build_index(**kwargs):
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    # Must not raise (KeyError regression).
    await GraphIndexOrchestrator(uow).execute(_make_request(frozenset({5})))

    # Slot must remain unchanged (None).
    assert rag.slot is None

    # No clear() must have been called — no slot operations on a normal new-index run.
    assert not any(s.clear_called for s in storages_created)
