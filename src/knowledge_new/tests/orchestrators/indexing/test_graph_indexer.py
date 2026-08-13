import asyncio
import types
from typing import Literal

import pandas
import pytest
from application.orchestrators.indexing.strategies import graph_indexer
from application.orchestrators.indexing.strategies.graph_indexer import GraphIndexOrchestrator
from domain.enums import DocumentStatusEnum, IndexStatusEnum, RAGStrategy
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
        self.status_updates: list[tuple[frozenset[int], str]] = []
        self.build_index_call_count: int = 0
        self._document_statuses: dict[int, str] = {}

    async def get_rag(self, rag_id: int) -> Rag | None:
        if self._get_rag_raises is not None:
            raise self._get_rag_raises
        return self._rag

    async def get_config(self, rag_id: int) -> object | None:
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
    doc_status = "completed" if request_has_completed_doc else "new"
    document = _text_document(10, status=doc_status)
    config = object()
    repo = FakeGraphRagRepo(rag=rag, config=config, documents=[document])
    uow = FakeUoW(repo)

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
