import asyncio
import types
from typing import Literal

import pandas
import pytest
from enums import IndexStatusEnum, RAGStrategy
from errors import DocumentNotFoundError, GraphRagConfigNotFoundError, RagNotFoundError
from graphrag_input import TextDocument
from models import IndexRequest, Rag
from orchestrators.indexing.strategies import graph_indexer
from orchestrators.indexing.strategies.graph_indexer import GraphIndexer


def _result(workflow: str, error: BaseException | None = None) -> types.SimpleNamespace:
    """Minimal stand-in for PipelineRunResult — only .workflow and .error are used."""
    return types.SimpleNamespace(workflow=workflow, error=error)


def _new_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.NEW, indexing_document_ids=set())


def _text_document(doc_id: int, *, status: str = "new", text: str = "hello world") -> TextDocument:
    """Construct a real TextDocument as the repository does, with a controllable status field."""
    return TextDocument(
        id=str(doc_id),
        text=text,
        title=f"doc_{doc_id}.txt",
        creation_date="2024-01-01T00:00:00",
        raw_data={"status": status},
    )


def _make_request(
    document_ids: frozenset[int], rag_id: int = 1
) -> IndexRequest:
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

    async def get_rag(self, rag_id: int) -> Rag | None:
        if self._get_rag_raises is not None:
            raise self._get_rag_raises
        return self._rag

    async def get_config(self, rag_id: int) -> object | None:
        return self._config

    async def get_documents(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        if self._get_documents_raises is not None:
            raise self._get_documents_raises
        return [d for d in self._documents if int(d.id) in ids]

    async def has_indexed_document(self, rag_id: int) -> bool:
        return self._has_indexed_db

    async def update_rag(self, rag: Rag) -> None:
        # Append only when status actually changes to avoid duplicate log entries.
        if not self.rag_status_log or self.rag_status_log[-1] != rag.status:
            self.rag_status_log.append(rag.status)

    async def update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: Literal["new", "indexed"],
    ) -> None:
        self.status_updates.append((frozenset(ids), status))


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
    await GraphIndexer(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert repo.status_updates == [(frozenset({7}), "indexed")]
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
    await GraphIndexer(uow).execute(request)

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
    "has_indexed_db, request_has_indexed, expected_is_update_run",
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, False),
    ],
    ids=[
        "db_indexed_request_new_expect_update",
        "db_indexed_request_indexed_expect_no_update",
        "db_new_request_new_expect_no_update",
        "db_new_request_indexed_expect_no_update",
    ],
)
async def test_is_update_run_computed_correctly(
    monkeypatch,
    has_indexed_db: bool,
    request_has_indexed: bool,
    expected_is_update_run: bool,
):
    rag = _new_rag()
    # When request_has_indexed is True, the document's raw_data status must be 'indexed'
    # to satisfy: has_indexed_document_in_request = any(d.raw_data['status'] == 'indexed' ...)
    doc_status = "indexed" if request_has_indexed else "new"
    document = _text_document(10, status=doc_status)
    config = object()
    repo = FakeGraphRagRepo(
        rag=rag,
        config=config,
        documents=[document],
        has_indexed_db=has_indexed_db,
    )
    uow = FakeUoW(repo)

    captured_is_update_run: list[bool] = []

    async def fake_build_index(**kwargs):
        captured_is_update_run.append(kwargs["is_update_run"])
        return [_result("extract_graph")]

    monkeypatch.setattr(graph_indexer, "build_index", fake_build_index)

    request = _make_request(frozenset({10}))
    await GraphIndexer(uow).execute(request)

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
        await GraphIndexer(uow).execute(request)

    # documents must NOT be marked indexed when indexing errors occurred
    assert repo.status_updates == []
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
        await GraphIndexer(uow).execute(request)

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
        await GraphIndexer(uow).execute(request)

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
        await GraphIndexer(uow).execute(request)

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
    await GraphIndexer(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED]
    assert repo.status_updates == []

    if cancel_scenario == "during_build_index":
        assert build_index_called == [True]
    else:
        # build_index never reached because commit raised before that point
        assert build_index_called == []
