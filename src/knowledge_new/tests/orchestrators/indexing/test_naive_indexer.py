import asyncio

import pytest
from application.commands import RunIndex
from application.orchestrators.indexing.strategies import naive_indexer
from application.orchestrators.indexing.strategies.naive_indexer import (
    NaiveIndexOrchestrator,
)
from domain.enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
)
from domain.errors import (
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    EmbeddingError,
    RagNotFoundError,
)
from domain.models import (
    ChunkingConfig,
    Document,
    EmbeddingConfig,
    IndexedChunk,
    PreviewChunk,
    Rag,
)


class FakeNaiveRagRepo:
    """In-memory repo for the indexing flow."""

    def __init__(
        self,
        *,
        embedding_config: EmbeddingConfig | None,
        documents: list[Document],
        rag: Rag | None = None,
        get_rag_raises: BaseException | None = None,
        get_documents_raises: BaseException | None = None,
    ):
        self._embedding_config = embedding_config
        self._documents = documents
        self._rag = rag
        self._get_rag_raises = get_rag_raises
        self._get_documents_raises = get_documents_raises
        self.doc_status_log: list[DocumentStatusEnum] = []
        self.rag_status_log: list[IndexStatusEnum] = []
        self.saved_indexed_chunks: list[tuple[int, list[IndexedChunk]]] = []

    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        return self._embedding_config

    async def get_rag(self, rag_id: int) -> Rag | None:
        if self._get_rag_raises is not None:
            raise self._get_rag_raises
        return self._rag

    async def update_rag(self, rag: Rag) -> None:
        if not self.rag_status_log or self.rag_status_log[-1] != rag.status:
            self.rag_status_log.append(rag.status)

    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[Document]:
        if self._get_documents_raises is not None:
            raise self._get_documents_raises
        return [d for d in self._documents if d.id in ids]

    async def has_completed_document(self, rag_id: int) -> bool:
        return any(d.status == DocumentStatusEnum.COMPLETED for d in self._documents)

    async def has_failed_document(self, rag_id: int) -> bool:
        return any(d.status == DocumentStatusEnum.FAILED for d in self._documents)

    async def has_outdated_document(self, rag_id: int) -> bool:
        return any(d.status == DocumentStatusEnum.OUTDATED for d in self._documents)

    async def update_document(self, rag_id: int, document: Document) -> None:
        self.doc_status_log.append(document.status)

    async def save_indexed_chunks(
        self, document_id: int, chunks: list[IndexedChunk]
    ) -> None:
        self.saved_indexed_chunks.append((document_id, list(chunks)))


class FakeUoW:
    """In-memory unit of work — re-enterable."""

    def __init__(
        self,
        repo: FakeNaiveRagRepo,
        *,
        commit_errors: list[BaseException] | None = None,
    ):
        self.naive_rag_repo = repo
        self._commit_errors: list[BaseException] | None = list(commit_errors or [])
        self.commit_count = 0

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


class FakeEmbedder:
    """Stands in for the external embedding-provider API."""

    def __init__(self, vector: list[float], *, raises: BaseException | None = None):
        self._vector = vector
        self._raises = raises
        self.embedded: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        if self._raises is not None:
            raise self._raises
        return self._vector


_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI,
    model="text-embedding-3-small",
)

_DUMMY_DOCUMENT = Document(
    id=1,
    name="doc.txt",
    content=b"alpha\n\nbeta",
    status=DocumentStatusEnum.NEW,
    config=ChunkingConfig(
        chunk_strategy=ChunkStrategyEnum.CHARACTER,
        chunk_size=50,
        chunk_overlap=0,
        extra={"character": {"regex": r"\n\n"}},
    ),
)


def _new_rag(rag_id: int = 1) -> Rag:
    return Rag(id=rag_id, status=IndexStatusEnum.NEW, indexing_document_ids=set())


async def test_index_success_full_flow_sets_document_and_rag_statuses(monkeypatch):
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, config: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.doc_status_log == [
        DocumentStatusEnum.PROCESSING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [
        IndexStatusEnum.PROCESSING,
        IndexStatusEnum.COMPLETED,
    ]
    assert rag.indexing_document_ids == set()
    assert embedder.embedded == ["alpha", "beta"]


async def test_index_skips_already_completed_document_with_unchanged_config(
    monkeypatch,
):
    config = ChunkingConfig(
        chunk_strategy=ChunkStrategyEnum.CHARACTER,
        chunk_size=50,
        chunk_overlap=0,
        extra={"character": {"regex": r"\n\n"}},
    )
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.COMPLETED,
        config=config,
        last_indexing_config=config,  # unchanged since last index → reindex not required
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.doc_status_log == []
    assert document.status == DocumentStatusEnum.COMPLETED
    assert embedder.embedded == []
    assert repo.saved_indexed_chunks == []
    assert repo.rag_status_log == [
        IndexStatusEnum.PROCESSING,
        IndexStatusEnum.COMPLETED,
    ]
    assert rag.indexing_document_ids == set()


async def test_index_success_skips_chunking_when_preview_chunks_exist(monkeypatch):
    preview_chunks = [PreviewChunk(text="alpha"), PreviewChunk(text="beta")]
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
        preview_chunks=preview_chunks,
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.doc_status_log == [
        DocumentStatusEnum.PROCESSING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [
        IndexStatusEnum.PROCESSING,
        IndexStatusEnum.COMPLETED,
    ]
    assert embedder.embedded == ["alpha", "beta"]
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert document.indexed_chunks == expected_indexed
    assert repo.saved_indexed_chunks == [(7, expected_indexed)]


async def test_index_rechunks_when_config_changed_despite_existing_preview_chunks(
    monkeypatch,
):
    stale_chunks = [PreviewChunk(text="stale")]
    previous_config = ChunkingConfig(
        chunk_strategy=ChunkStrategyEnum.CHARACTER,
        chunk_size=10,
        chunk_overlap=0,
    )
    current_config = ChunkingConfig(
        chunk_strategy=ChunkStrategyEnum.CHARACTER,
        chunk_size=50,
        chunk_overlap=0,
        extra={"character": {"regex": r"\n\n"}},
    )
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.COMPLETED,
        config=current_config,
        last_indexing_config=previous_config,  # differs → reindex required → re-chunk
        preview_chunks=stale_chunks,
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.doc_status_log == [
        DocumentStatusEnum.PROCESSING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [
        IndexStatusEnum.PROCESSING,
        IndexStatusEnum.COMPLETED,
    ]
    assert document.preview_chunks == []
    assert embedder.embedded == ["alpha", "beta"]
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert document.indexed_chunks == expected_indexed
    assert repo.saved_indexed_chunks == [(7, expected_indexed)]


@pytest.mark.parametrize(
    "get_rag_raises,get_documents_raises,commit_errors,expected_rag_log,expected_doc_log",
    [
        (
            asyncio.CancelledError(),
            None,
            None,
            [],
            [],
        ),
        (
            None,
            asyncio.CancelledError(),
            None,
            [IndexStatusEnum.CANCELLED],
            [],
        ),
        (
            None,
            None,
            [asyncio.CancelledError(), None],
            [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED],
            [],
        ),
        (
            None,
            None,
            [None, None, asyncio.CancelledError(), None],
            [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED],
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.COMPLETED],
        ),
    ],
    ids=["rag_fetch", "preparation", "processing_update", "document_update"],
)
async def test_cancellation_marks_rag_cancelled(
    monkeypatch,
    get_rag_raises,
    get_documents_raises,
    commit_errors,
    expected_rag_log,
    expected_doc_log,
):
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
        preview_chunks=[PreviewChunk(text="alpha"), PreviewChunk(text="beta")],
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG,
        documents=[document],
        rag=rag,
        get_rag_raises=get_rag_raises,
        get_documents_raises=get_documents_raises,
    )
    uow = FakeUoW(repo, commit_errors=commit_errors)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)
    assert repo.rag_status_log == expected_rag_log
    assert repo.doc_status_log == expected_doc_log


@pytest.mark.parametrize(
    "doc_kwargs,embed_raises,expected_doc_log",
    [
        (
            {
                "name": "doc.csv",
                "content": b"\xff\xfe",
                "status": DocumentStatusEnum.NEW,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CSV,
                    chunk_size=50,
                    chunk_overlap=0,
                ),
            },
            None,
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.FAILED],
        ),
        (
            {
                "name": "doc.txt",
                "content": b"some text",
                "status": DocumentStatusEnum.NEW,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CHARACTER,
                    chunk_size=50,
                    chunk_overlap=0,
                    extra={"character": {"regex": "["}},
                ),
            },
            None,
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.FAILED],
        ),
        (
            {
                "name": "doc.txt",
                "content": b"\n\n",
                "status": DocumentStatusEnum.NEW,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CHARACTER,
                    chunk_size=50,
                    chunk_overlap=0,
                    extra={"character": {"regex": r"\n\n"}},
                ),
            },
            None,
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.FAILED],
        ),
        (
            {
                "name": "doc.txt",
                "content": b"alpha\n\nbeta",
                "status": DocumentStatusEnum.NEW,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CHARACTER,
                    chunk_size=50,
                    chunk_overlap=0,
                    extra={"character": {"regex": r"\n\n"}},
                ),
                "preview_chunks": [
                    PreviewChunk(text="alpha"),
                    PreviewChunk(text="beta"),
                ],
            },
            EmbeddingError(embedder="FakeEmbedder"),
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.FAILED],
        ),
    ],
    ids=[
        "extraction_failure",
        "chunking_failure",
        "no_chunks_produced",
        "embedding_failure",
    ],
)
async def test_document_error_marks_document_failed_and_rag_failed(
    monkeypatch, doc_kwargs, embed_raises, expected_doc_log
):
    document = Document(id=7, **doc_kwargs)
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2], raises=embed_raises)
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert document.status == DocumentStatusEnum.FAILED
    assert document.error_message  # populated by mark_as_failed(error)
    assert repo.doc_status_log == expected_doc_log
    # no document completed → rag ends FAILED
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.FAILED]


async def test_index_partial_when_one_document_succeeds_and_one_fails(monkeypatch):
    good_doc = Document(
        id=1,
        name="good.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
        preview_chunks=[PreviewChunk(text="alpha"), PreviewChunk(text="beta")],
    )
    bad_doc = Document(
        id=2,
        name="bad.txt",
        content=b"some text",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": "["}},  # invalid regex → ChunkingError
        ),
    )
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[good_doc, bad_doc], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({1, 2}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert good_doc.status == DocumentStatusEnum.COMPLETED
    assert bad_doc.status == DocumentStatusEnum.FAILED
    assert repo.doc_status_log == [
        DocumentStatusEnum.PROCESSING,
        DocumentStatusEnum.COMPLETED,
        DocumentStatusEnum.PROCESSING,
        DocumentStatusEnum.FAILED,
    ]
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert repo.saved_indexed_chunks == [(1, expected_indexed)]
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.PARTIAL]


@pytest.mark.parametrize(
    "embedding_config,documents,document_ids,expected_exc",
    [
        (
            None,
            [_DUMMY_DOCUMENT],
            frozenset({1}),
            EmbeddingConfigNotFoundError,
        ),
        (
            _EMBEDDING_CONFIG,
            [],
            frozenset(),
            DocumentNotFoundError,
        ),
    ],
    ids=["embedding_config_not_found", "no_documents"],
)
async def test_top_level_error_marks_rag_failed_and_reraises(
    monkeypatch,
    embedding_config,
    documents,
    document_ids,
    expected_exc,
):
    rag = _new_rag()
    repo = FakeNaiveRagRepo(
        embedding_config=embedding_config, documents=documents, rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(rag_id=1, document_ids=document_ids, embedding_api_key="sk-test")

    with pytest.raises(expected_exc):
        await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == [IndexStatusEnum.FAILED]
    assert repo.doc_status_log == []
    assert embedder.embedded == []


async def test_missing_rag_raises_and_does_not_mark_anything(monkeypatch):
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[], rag=None)
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=999, document_ids=frozenset(), embedding_api_key="sk-test"
    )

    with pytest.raises(RagNotFoundError):
        await NaiveIndexOrchestrator(uow).execute(request)

    assert repo.rag_status_log == []


def _static_document(status: DocumentStatusEnum, doc_id: int) -> Document:
    """A document excluded from `document_ids` — sits in the collection untouched by this run."""
    return Document(
        id=doc_id,
        name="other.txt",
        content=b"irrelevant",
        status=status,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
        ),
    )


def _processed_document(outcome: str, doc_id: int) -> Document:
    """The document actually run through `on_execute` this call; ends up COMPLETED or FAILED."""
    base_config = ChunkingConfig(
        chunk_strategy=ChunkStrategyEnum.CHARACTER,
        chunk_size=50,
        chunk_overlap=0,
        extra={"character": {"regex": r"\n\n" if outcome == "completed" else "["}},
    )
    if outcome == "completed":
        return Document(
            id=doc_id,
            name="doc.txt",
            content=b"alpha\n\nbeta",
            status=DocumentStatusEnum.COMPLETED,
            config=base_config,
            last_indexing_config=base_config,  # unchanged → skipped, stays COMPLETED
        )
    return Document(
        id=doc_id,
        name="doc.txt",
        content=b"some text",
        status=DocumentStatusEnum.NEW,
        config=base_config,  # invalid regex → chunker fails → mark_failed()
    )


@pytest.mark.parametrize(
    "doc1_status,doc2_outcome,expected_status",
    [
        (DocumentStatusEnum.NEW, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.NEW, "failed", IndexStatusEnum.FAILED),
        (DocumentStatusEnum.PROCESSING, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.PROCESSING, "failed", IndexStatusEnum.FAILED),
        (DocumentStatusEnum.COMPLETED, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.COMPLETED, "failed", IndexStatusEnum.PARTIAL),
        (DocumentStatusEnum.FAILED, "completed", IndexStatusEnum.PARTIAL),
        (DocumentStatusEnum.FAILED, "failed", IndexStatusEnum.FAILED),
        # A remaining OUTDATED document makes the rag OUTDATED regardless of doc2 outcome
        (DocumentStatusEnum.OUTDATED, "completed", IndexStatusEnum.OUTDATED),
        (DocumentStatusEnum.OUTDATED, "failed", IndexStatusEnum.OUTDATED),
    ],
    ids=[
        "doc1=new,doc2=completed",
        "doc1=new,doc2=failed",
        "doc1=processing,doc2=completed",
        "doc1=processing,doc2=failed",
        "doc1=completed,doc2=completed",
        "doc1=completed,doc2=failed",
        "doc1=failed,doc2=completed",
        "doc1=failed,doc2=failed",
        "doc1=outdated,doc2=completed",
        "doc1=outdated,doc2=failed",
    ],
)
async def test_finalize_rag_status_considers_documents_outside_ids(
    monkeypatch, doc1_status, doc2_outcome, expected_status
):
    doc1 = _static_document(doc1_status, doc_id=1)  # excluded from this run
    doc2 = _processed_document(doc2_outcome, doc_id=2)  # the one actually indexed
    rag = _new_rag()

    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[doc1, doc2], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({2}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert doc1.status == doc1_status  # untouched — outside document_ids
    assert repo.rag_status_log[-1] == expected_status
    assert rag.indexing_document_ids == set()


async def test_outdated_reasons_cleared_when_no_outdated_document_remains(monkeypatch):
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
    )
    rag = Rag(
        id=1,
        status=IndexStatusEnum.NEW,
        indexing_document_ids=set(),
        outdated_reasons={"doc_7": "content_changed"},
    )
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG, documents=[document], rag=rag
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({7}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert rag.outdated_reasons == {}
    assert repo.rag_status_log[-1] == IndexStatusEnum.COMPLETED


async def test_outdated_reasons_preserved_when_outdated_document_remains(monkeypatch):
    outdated_doc = _static_document(DocumentStatusEnum.OUTDATED, doc_id=1)
    active_doc = Document(
        id=2,
        name="active.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
    )
    rag = Rag(
        id=1,
        status=IndexStatusEnum.NEW,
        indexing_document_ids=set(),
        outdated_reasons={"doc_1": "source_changed"},
    )
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG,
        documents=[outdated_doc, active_doc],
        rag=rag,
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(
        naive_indexer, "build_embedder", lambda provider, api_key, cfg: embedder
    )

    request = RunIndex(
        rag_id=1, document_ids=frozenset({2}), embedding_api_key="sk-test"
    )

    await NaiveIndexOrchestrator(uow).execute(request)

    assert rag.outdated_reasons == {"doc_1": "source_changed"}
    assert repo.rag_status_log[-1] == IndexStatusEnum.OUTDATED
