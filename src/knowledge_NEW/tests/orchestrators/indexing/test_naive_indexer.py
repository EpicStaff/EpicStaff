import pytest
import asyncio

from enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
    RAGStrategy,
)
from models import ChunkingConfig, Document, EmbeddingConfig, IndexedChunk, IndexRequest, PreviewChunk
from orchestrators.indexing.strategies import naive_indexer
from orchestrators.indexing.strategies.naive_indexer import NaiveIndexer


class FakeNaiveRagRepo:
    """In-memory repo for the indexing flow.

    doc_status_log / rag_status_log record status at each update call so tests can
    assert the order of transitions for both the document and the RAG.
    get_all_documents_raises injects a failure at the preparation stage.
    """

    def __init__(
        self,
        *,
        embedding_config: EmbeddingConfig | None,
        documents: list[Document],
        get_all_documents_raises: BaseException | None = None,
    ):
        self._embedding_config = embedding_config
        self._documents = documents
        self._get_all_documents_raises = get_all_documents_raises
        self.doc_status_log: list[DocumentStatusEnum] = []
        self.rag_status_log: list[IndexStatusEnum] = []
        self.saved_indexed_chunks: list[tuple[int, list[IndexedChunk]]] = []

    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        return self._embedding_config

    async def get_all_documents(self, rag_id: int) -> list[Document]:
        if self._get_all_documents_raises is not None:
            raise self._get_all_documents_raises
        return self._documents

    async def update_rag_status(self, rag_id: int, status: IndexStatusEnum) -> None:
        self.rag_status_log.append(status)

    async def update_document(self, rag_id: int, document: Document) -> None:
        self.doc_status_log.append(document.status)

    async def save_indexed_chunks(self, document_id: int, chunks: list[IndexedChunk]) -> None:
        self.saved_indexed_chunks.append((document_id, list(chunks)))


class FakeUoW:
    """In-memory unit of work — re-enterable (the indexer opens it many times).

    commit_errors is consumed one entry per commit() call: a non-None entry is raised,
    letting a test inject a failure at a specific persistence step.
    """

    def __init__(self, repo: FakeNaiveRagRepo, *, commit_errors: list[BaseException | None] | None = None):
        self.naive_rag_repo = repo
        self._commit_errors: list[BaseException | None] = list(commit_errors or [])
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
    """Stands in for the external embedding-provider API.

    Returns a fixed opaque vector, or raises `raises` to simulate an embedding failure.
    """

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
    api_key="test-key",
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
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[document])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, config: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None
    assert repo.doc_status_log == [
        DocumentStatusEnum.CHUNKING,
        DocumentStatusEnum.CHUNKED,
        DocumentStatusEnum.INDEXING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert embedder.embedded == ["alpha", "beta"]


async def test_index_skips_already_completed_document_with_unchanged_config(monkeypatch):
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
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[document])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None
    assert repo.doc_status_log == []
    assert document.status == DocumentStatusEnum.COMPLETED
    assert embedder.embedded == []
    assert repo.saved_indexed_chunks == []
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]


async def test_index_success_skips_chunking_when_preview_chunks_exist(monkeypatch):
    preview_chunks = [PreviewChunk(text="alpha"), PreviewChunk(text="beta")]
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.CHUNKED,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
        preview_chunks=preview_chunks,
    )
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[document])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None
    # chunking stage skipped — straight to INDEXING → COMPLETED, no CHUNKING/CHUNKED
    assert repo.doc_status_log == [
        DocumentStatusEnum.INDEXING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    # existing preview chunks embedded as-is
    assert embedder.embedded == ["alpha", "beta"]
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert document.indexed_chunks == expected_indexed
    assert repo.saved_indexed_chunks == [(7, expected_indexed)]


async def test_index_rechunks_when_config_changed_despite_existing_preview_chunks(monkeypatch):
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
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[document])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None
    # config changed → full re-chunk even though preview chunks already existed
    assert repo.doc_status_log == [
        DocumentStatusEnum.CHUNKING,
        DocumentStatusEnum.CHUNKED,
        DocumentStatusEnum.INDEXING,
        DocumentStatusEnum.COMPLETED,
    ]
    assert document.status == DocumentStatusEnum.COMPLETED
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    # stale preview chunks replaced; the NEW ones embedded (not "stale")
    new_preview = [PreviewChunk(text="alpha"), PreviewChunk(text="beta")]
    assert document.preview_chunks == new_preview
    assert embedder.embedded == ["alpha", "beta"]
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert document.indexed_chunks == expected_indexed
    assert repo.saved_indexed_chunks == [(7, expected_indexed)]


@pytest.mark.parametrize(
    "get_all_documents_raises,commit_errors,expected_rag_log,expected_doc_log",
    [
        # cancel in preparation (before PROCESSING is written)
        (
                asyncio.CancelledError(),
                None,
                [IndexStatusEnum.CANCELLED],
                [],
        ),
        # cancel while committing the PROCESSING status
        (
                None,
                [asyncio.CancelledError(), None],
                [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED],
                [],
        ),
        # cancel mid-document (commit of the INDEXING update)
        (
                None,
                [None, asyncio.CancelledError(), None],
                [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED],
                [DocumentStatusEnum.INDEXING],
        ),
    ],
    ids=["preparation", "processing_update", "document_update"],
)
async def test_cancellation_marks_rag_cancelled(
    monkeypatch,
    get_all_documents_raises,
    commit_errors,
    expected_rag_log,
    expected_doc_log,
):
    document = Document(
        id=7,
        name="doc.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.CHUNKED,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=50,
            chunk_overlap=0,
            extra={"character": {"regex": r"\n\n"}},
        ),
        preview_chunks=[PreviewChunk(text="alpha"), PreviewChunk(text="beta")],
    )
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG,
        documents=[document],
        get_all_documents_raises=get_all_documents_raises,
    )
    uow = FakeUoW(repo, commit_errors=commit_errors)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None  # execute swallows CancelledError, returns None
    assert repo.rag_status_log == expected_rag_log
    assert repo.doc_status_log == expected_doc_log


from enums import DocumentErrorCode
from errors import EmbeddingError, EmbeddingConfigNotFoundError, DocumentNotFoundError


@pytest.mark.parametrize(
    "doc_kwargs,embed_raises,expected_error_code,expected_doc_log",
    [
        # extractor fails on invalid UTF-8 (.csv) → CHUNKING_FAILED
        (
            {
                "name": "doc.csv",
                "content": b"\xff\xfe",
                "status": DocumentStatusEnum.NEW,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CSV, chunk_size=50, chunk_overlap=0
                ),
            },
            None,
            DocumentErrorCode.CHUNKING_FAILED,
            [DocumentStatusEnum.CHUNKING, DocumentStatusEnum.FAILED],
        ),
        # chunker fails on invalid regex → CHUNKING_FAILED
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
            DocumentErrorCode.CHUNKING_FAILED,
            [DocumentStatusEnum.CHUNKING, DocumentStatusEnum.FAILED],
        ),
        # chunker yields nothing → NoPreviewChunksProducedError → UNKNOWN
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
            DocumentErrorCode.CHUNKING_FAILED,
            [DocumentStatusEnum.CHUNKING, DocumentStatusEnum.FAILED],
        ),
        # embedder fails on an already-chunked doc → EMBEDDING_FAILED
        (
            {
                "name": "doc.txt",
                "content": b"alpha\n\nbeta",
                "status": DocumentStatusEnum.CHUNKED,
                "config": ChunkingConfig(
                    chunk_strategy=ChunkStrategyEnum.CHARACTER,
                    chunk_size=50,
                    chunk_overlap=0,
                    extra={"character": {"regex": r"\n\n"}},
                ),
                "preview_chunks": [PreviewChunk(text="alpha"), PreviewChunk(text="beta")],
            },
            EmbeddingError(embedder="FakeEmbedder"),
            DocumentErrorCode.EMBEDDING_FAILED,
            [DocumentStatusEnum.INDEXING, DocumentStatusEnum.FAILED],
        ),
    ],
    ids=["extraction_failure", "chunking_failure", "no_chunks_produced", "embedding_failure"],
)
async def test_document_error_marks_document_failed_and_rag_failed(
    monkeypatch,
    doc_kwargs,
    embed_raises,
    expected_error_code,
    expected_doc_log,
):
    document = Document(id=7, **doc_kwargs)
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, documents=[document])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2], raises=embed_raises)
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None  # per-document errors are caught, NOT propagated
    assert document.status == DocumentStatusEnum.FAILED
    assert document.error_code == expected_error_code
    assert document.error_message  # populated via classify → format_error_message
    assert repo.doc_status_log == expected_doc_log
    # no document completed → rag ends FAILED
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.FAILED]


async def test_index_warning_when_one_document_succeeds_and_one_fails(monkeypatch):
    good_doc = Document(
        id=1,
        name="good.txt",
        content=b"alpha\n\nbeta",
        status=DocumentStatusEnum.CHUNKED,
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
    repo = FakeNaiveRagRepo(
        embedding_config=_EMBEDDING_CONFIG,
        documents=[good_doc, bad_doc],
    )
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    result = await NaiveIndexer(uow).execute(request)

    assert result is None
    # per-document outcomes
    assert good_doc.status == DocumentStatusEnum.COMPLETED
    assert bad_doc.status == DocumentStatusEnum.FAILED
    assert bad_doc.error_code == DocumentErrorCode.CHUNKING_FAILED
    # processing order across both documents
    assert repo.doc_status_log == [
        DocumentStatusEnum.INDEXING,
        DocumentStatusEnum.COMPLETED,
        DocumentStatusEnum.CHUNKING,
        DocumentStatusEnum.FAILED,
    ]
    # only the good doc's chunks were persisted
    expected_indexed = [
        IndexedChunk(text="alpha", vector=[0.1, 0.2]),
        IndexedChunk(text="beta", vector=[0.1, 0.2]),
    ]
    assert repo.saved_indexed_chunks == [(1, expected_indexed)]
    # mix of completed + failed → rag ends WARNING
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.WARNING]


@pytest.mark.parametrize(
    "embedding_config,documents,expected_exc",
    [
        # missing embedding config → fails before build_embedder
        (None, [_DUMMY_DOCUMENT], EmbeddingConfigNotFoundError),
        # no documents in the RAG → fails right after the embedder is built
        (_EMBEDDING_CONFIG, [], DocumentNotFoundError),
    ],
    ids=["embedding_config_not_found", "no_documents"],
)
async def test_top_level_error_marks_rag_failed_and_reraises(
    monkeypatch,
    embedding_config,
    documents,
    expected_exc,
):
    repo = FakeNaiveRagRepo(embedding_config=embedding_config, documents=documents)
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2])
    monkeypatch.setattr(naive_indexer, "build_embedder", lambda provider, cfg: embedder)

    request = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)

    with pytest.raises(expected_exc):
        await NaiveIndexer(uow).execute(request)

    # on_error ran: rag marked FAILED — and ONLY that (PROCESSING was never reached)
    assert repo.rag_status_log == [IndexStatusEnum.FAILED]
    assert repo.doc_status_log == []
    assert embedder.embedded == []
