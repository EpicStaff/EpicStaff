import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from application.commands import RunIndex
from application.orchestrators.indexing.strategies import naive_indexer
from application.orchestrators.indexing.strategies.naive_indexer import NaiveIndexOrchestrator
from domain.enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
)
from domain.errors import DocumentNotFoundError, EmbeddingConfigNotFoundError, RagNotFoundError
from domain.models import (
    ChunkingConfig,
    Document,
    EmbeddingConfig,
    IndexedChunk,
    PreviewChunk,
    Rag,
)
from domain.usage import IndexingRunUsage
from infrastructure.naive.embedders.strategies import litellm_embedder

VECTOR = [0.1, 0.2]
DEFAULT_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI, model="text-embedding-3-small"
)


class FakeNaiveRagRepo:
    """In-memory repo for the indexing flow; records every persisted status."""

    def __init__(
        self,
        *,
        documents: list[Document],
        rag: Rag | None,
        embedding_config: EmbeddingConfig | None = DEFAULT_EMBEDDING_CONFIG,
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
        self.usage_runs: list[IndexingRunUsage] = []

    async def add_indexing_usage(self, rag_id: int, run: IndexingRunUsage) -> None:
        self.usage_runs.append(run)

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

    async def save_indexed_chunks(self, document_id: int, chunks: list[IndexedChunk]) -> None:
        self.saved_indexed_chunks.append((document_id, list(chunks)))


class FakeUoW:
    def __init__(self, repo: FakeNaiveRagRepo):
        self.naive_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        pass


def _provider_response(prompt_tokens: int | None = None):
    usage = None if prompt_tokens is None else type("Usage", (), {"prompt_tokens": prompt_tokens})()
    return type("Resp", (), {"data": [{"embedding": VECTOR}], "usage": usage})()


@pytest.fixture
def embedding_api():
    """litellm's embedding call, the boundary to the provider's HTTP API."""
    mock = AsyncMock(return_value=_provider_response())
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        yield mock


def _embedded_texts(embedding_api) -> list[str]:
    return [call.kwargs["input"][0] for call in embedding_api.await_args_list]


PARAGRAPH_CONFIG = ChunkingConfig(
    chunk_strategy=ChunkStrategyEnum.CHARACTER,
    chunk_size=50,
    chunk_overlap=0,
    extra={"character": {"regex": r"\n\n"}},
)


def _document(doc_id: int = 7, **overrides) -> Document:
    """A text document whose content chunks into "alpha" and "beta"."""
    return Document(
        **{
            "id": doc_id,
            "name": "doc.txt",
            "content": b"alpha\n\nbeta",
            "status": DocumentStatusEnum.NEW,
            "config": PARAGRAPH_CONFIG,
            **overrides,
        }
    )


def _broken_json_document(doc_id: int) -> Document:
    return Document(
        id=doc_id,
        name="doc.json",
        content=b"{not valid",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(chunk_strategy=ChunkStrategyEnum.JSON, chunk_size=50, chunk_overlap=0),
    )


def _new_rag(**overrides) -> Rag:
    return Rag(
        **{"id": 1, "status": IndexStatusEnum.NEW, "indexing_document_ids": set(), **overrides}
    )


async def _index(
    repo: FakeNaiveRagRepo, *document_ids: int, embedding_extra_headers: dict[str, str] | None = None
):
    request = RunIndex(
        rag_id=1,
        document_ids=frozenset(document_ids),
        embedding_api_key="sk-test",
        embedding_extra_headers=embedding_extra_headers or {},
    )
    await NaiveIndexOrchestrator(FakeUoW(repo)).execute(request)


def _indexed(*texts: str) -> list[IndexedChunk]:
    return [IndexedChunk(text=text, vector=VECTOR) for text in texts]


async def test_new_document_is_chunked_embedded_and_saved(embedding_api):
    document = _document()
    rag = _new_rag()
    repo = FakeNaiveRagRepo(documents=[document], rag=rag)

    await _index(repo, 7)

    assert _embedded_texts(embedding_api) == ["alpha", "beta"]
    assert embedding_api.await_args.kwargs["api_key"] == "sk-test"
    assert repo.saved_indexed_chunks == [(7, _indexed("alpha", "beta"))]
    assert repo.doc_status_log == [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.COMPLETED]
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert rag.indexing_document_ids == set()


async def test_document_already_indexed_with_the_same_config_is_skipped(embedding_api):
    document = _document(status=DocumentStatusEnum.COMPLETED, last_indexing_config=PARAGRAPH_CONFIG)
    rag = _new_rag()
    repo = FakeNaiveRagRepo(documents=[document], rag=rag)

    await _index(repo, 7)

    assert _embedded_texts(embedding_api) == []
    assert repo.saved_indexed_chunks == []
    assert repo.doc_status_log == []
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.COMPLETED]
    assert rag.indexing_document_ids == set()


async def test_existing_preview_chunks_are_indexed_instead_of_rechunking(embedding_api):
    """Preview chunks the user already reviewed are what gets indexed."""
    document = _document(preview_chunks=[PreviewChunk(text="reviewed chunk")])
    repo = FakeNaiveRagRepo(documents=[document], rag=_new_rag())

    await _index(repo, 7)

    assert _embedded_texts(embedding_api) == ["reviewed chunk"]
    assert repo.saved_indexed_chunks == [(7, _indexed("reviewed chunk"))]


async def test_changed_config_rechunks_despite_existing_preview_chunks(embedding_api):
    document = _document(
        status=DocumentStatusEnum.COMPLETED,
        last_indexing_config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER, chunk_size=10, chunk_overlap=0
        ),
        preview_chunks=[PreviewChunk(text="stale")],
    )
    repo = FakeNaiveRagRepo(documents=[document], rag=_new_rag())

    await _index(repo, 7)

    assert _embedded_texts(embedding_api) == ["alpha", "beta"]
    assert repo.saved_indexed_chunks == [(7, _indexed("alpha", "beta"))]
    assert repo.doc_status_log[-1] == DocumentStatusEnum.COMPLETED


@pytest.mark.parametrize(
    ("cancelled_at", "expected_rag_log", "expected_doc_log"),
    [
        ("loading the rag", [], []),
        ("loading the documents", [IndexStatusEnum.CANCELLED], []),
        (
            "embedding",
            [IndexStatusEnum.PROCESSING, IndexStatusEnum.CANCELLED],
            # The document is put back to the status it had before this run.
            [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.NEW],
        ),
    ],
)
async def test_cancelled_run_marks_rag_cancelled_and_restores_the_document(
    embedding_api, cancelled_at, expected_rag_log, expected_doc_log
):
    if cancelled_at == "embedding":
        embedding_api.side_effect = asyncio.CancelledError()
    repo = FakeNaiveRagRepo(
        documents=[_document()],
        rag=_new_rag(),
        get_rag_raises=asyncio.CancelledError() if cancelled_at == "loading the rag" else None,
        get_documents_raises=(
            asyncio.CancelledError() if cancelled_at == "loading the documents" else None
        ),
    )

    await _index(repo, 7)

    assert repo.rag_status_log == expected_rag_log
    assert repo.doc_status_log == expected_doc_log
    assert repo.saved_indexed_chunks == []


CSV_CONFIG = ChunkingConfig(chunk_strategy=ChunkStrategyEnum.CSV, chunk_size=50, chunk_overlap=0)


@pytest.mark.parametrize(
    ("document", "provider_error"),
    [
        (_document(name="doc.csv", content=b"\xff\xfe", config=CSV_CONFIG), None),
        (_broken_json_document(7), None),
        (_document(content=b"\n\n"), None),
        (_document(), RuntimeError("provider down")),
    ],
    ids=["extraction_failure", "chunking_failure", "no_chunks_produced", "embedding_failure"],
)
async def test_document_failure_marks_document_and_rag_failed(
    embedding_api, document, provider_error
):
    embedding_api.side_effect = provider_error
    repo = FakeNaiveRagRepo(documents=[document], rag=_new_rag())

    await _index(repo, 7)

    assert document.status == DocumentStatusEnum.FAILED
    assert document.error_message
    assert repo.doc_status_log == [DocumentStatusEnum.PROCESSING, DocumentStatusEnum.FAILED]
    assert repo.saved_indexed_chunks == []
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.FAILED]


async def test_one_failing_document_does_not_stop_the_others(embedding_api):
    good_document = _document(1)
    bad_document = _broken_json_document(2)
    repo = FakeNaiveRagRepo(documents=[good_document, bad_document], rag=_new_rag())

    await _index(repo, 1, 2)

    assert good_document.status == DocumentStatusEnum.COMPLETED
    assert bad_document.status == DocumentStatusEnum.FAILED
    assert repo.saved_indexed_chunks == [(1, _indexed("alpha", "beta"))]
    assert repo.rag_status_log == [IndexStatusEnum.PROCESSING, IndexStatusEnum.PARTIAL]


@pytest.mark.parametrize(
    ("embedding_config", "documents", "expected_error"),
    [
        (None, [_document()], EmbeddingConfigNotFoundError),
        (DEFAULT_EMBEDDING_CONFIG, [], DocumentNotFoundError),
    ],
    ids=["embedding_config_not_found", "no_documents"],
)
async def test_unusable_rag_is_marked_failed_and_the_error_raised(
    embedding_api, embedding_config, documents, expected_error
):
    repo = FakeNaiveRagRepo(
        documents=documents, rag=_new_rag(), embedding_config=embedding_config
    )

    with pytest.raises(expected_error):
        await _index(repo, 7)

    assert repo.rag_status_log == [IndexStatusEnum.FAILED]
    assert repo.doc_status_log == []
    assert _embedded_texts(embedding_api) == []


async def test_missing_rag_raises_and_marks_nothing(embedding_api):
    repo = FakeNaiveRagRepo(documents=[], rag=None)

    with pytest.raises(RagNotFoundError):
        await _index(repo, 7)

    assert repo.rag_status_log == []


@pytest.mark.parametrize(
    ("other_document_status", "indexed_document", "expected_status"),
    [
        (DocumentStatusEnum.NEW, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.NEW, "failed", IndexStatusEnum.FAILED),
        (DocumentStatusEnum.PROCESSING, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.PROCESSING, "failed", IndexStatusEnum.FAILED),
        (DocumentStatusEnum.COMPLETED, "completed", IndexStatusEnum.COMPLETED),
        (DocumentStatusEnum.COMPLETED, "failed", IndexStatusEnum.PARTIAL),
        (DocumentStatusEnum.FAILED, "completed", IndexStatusEnum.PARTIAL),
        (DocumentStatusEnum.FAILED, "failed", IndexStatusEnum.FAILED),
        (DocumentStatusEnum.OUTDATED, "completed", IndexStatusEnum.OUTDATED),
        (DocumentStatusEnum.OUTDATED, "failed", IndexStatusEnum.OUTDATED),
    ],
)
async def test_rag_status_accounts_for_documents_outside_the_run(
    embedding_api, other_document_status, indexed_document, expected_status
):
    other_document = Document(
        id=1,
        name="other.txt",
        content=b"irrelevant",
        status=other_document_status,
        config=PARAGRAPH_CONFIG,
    )
    if indexed_document == "completed":
        indexed = _document(2)
    else:
        indexed = _broken_json_document(2)
    rag = _new_rag()
    repo = FakeNaiveRagRepo(documents=[other_document, indexed], rag=rag)

    await _index(repo, 2)

    assert other_document.status == other_document_status
    assert repo.rag_status_log[-1] == expected_status
    assert rag.indexing_document_ids == set()


@pytest.mark.parametrize(
    ("other_documents", "expected_reasons", "expected_status"),
    [
        ([], {}, IndexStatusEnum.COMPLETED),
        (
            [Document(id=1, name="old.txt", content=b"x", status=DocumentStatusEnum.OUTDATED,
                      config=PARAGRAPH_CONFIG)],
            {"doc_1": "source_changed"},
            IndexStatusEnum.OUTDATED,
        ),
    ],
    ids=["no-outdated-document-left", "outdated-document-remains"],
)
async def test_outdated_reasons_are_kept_only_while_an_outdated_document_remains(
    embedding_api, other_documents, expected_reasons, expected_status
):
    rag = _new_rag(outdated_reasons={"doc_1": "source_changed"})
    repo = FakeNaiveRagRepo(documents=[*other_documents, _document(2)], rag=rag)

    await _index(repo, 2)

    assert rag.outdated_reasons == expected_reasons
    assert repo.rag_status_log[-1] == expected_status


async def test_embedding_extra_headers_reach_the_embedding_provider(embedding_api, monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    repo = FakeNaiveRagRepo(documents=[_document()], rag=_new_rag())

    await _index(repo, 7, embedding_extra_headers={"X-Gateway-Key": "resolved-value"})

    assert embedding_api.await_args.kwargs["extra_headers"] == {"X-Gateway-Key": "resolved-value"}


async def test_run_records_embedding_tokens_and_priced_cost(embedding_api, monkeypatch):
    embedding_api.return_value = _provider_response(prompt_tokens=10)
    monkeypatch.setattr(naive_indexer, "embedding_cost", lambda model, tokens: tokens * 1e-7)
    repo = FakeNaiveRagRepo(documents=[_document()], rag=_new_rag())

    await _index(repo, 7)

    (run,) = repo.usage_runs
    assert run.embedding_tokens == 20  # two chunks, 10 tokens each
    assert run.llm_input_tokens is None
    assert run.llm_output_tokens is None
    assert run.cost_usd == 20 * 1e-7


async def test_run_records_null_cost_for_unpriced_embedding_model(embedding_api):
    embedding_api.return_value = _provider_response(prompt_tokens=10)
    unpriced = DEFAULT_EMBEDDING_CONFIG.model_copy(update={"model": "no-such-embedding-model"})
    repo = FakeNaiveRagRepo(documents=[_document()], rag=_new_rag(), embedding_config=unpriced)

    await _index(repo, 7)

    (run,) = repo.usage_runs
    assert run.embedding_tokens == 20
    assert run.cost_usd is None


async def test_run_records_tokens_consumed_before_a_chunk_fails(embedding_api):
    embedding_api.side_effect = [_provider_response(prompt_tokens=10), RuntimeError("provider down")]
    repo = FakeNaiveRagRepo(documents=[_document()], rag=_new_rag())

    await _index(repo, 7)

    (run,) = repo.usage_runs
    assert run.embedding_tokens == 10


async def test_run_that_consumed_nothing_records_no_usage(embedding_api):
    document = _document(status=DocumentStatusEnum.COMPLETED, last_indexing_config=PARAGRAPH_CONFIG)
    repo = FakeNaiveRagRepo(documents=[document], rag=_new_rag())

    await _index(repo, 7)

    assert repo.usage_runs == []


async def test_cancelled_run_records_tokens_consumed_so_far(embedding_api):
    embedding_api.side_effect = [_provider_response(prompt_tokens=10), asyncio.CancelledError()]
    repo = FakeNaiveRagRepo(documents=[_document()], rag=_new_rag())

    await _index(repo, 7)

    (run,) = repo.usage_runs
    assert run.embedding_tokens == 10
