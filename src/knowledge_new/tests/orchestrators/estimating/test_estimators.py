import pytest
from application.commands import GetIndexEstimate
from application.orchestrators.estimating import build_estimator
from application.orchestrators.estimating.strategies import NaiveEstimateOrchestrator
from domain.enums import (
    ChunkStrategyEnum,
    DocumentStatusEnum,
    EmbedderProviderEnum,
    IndexStatusEnum,
    RAGStrategy,
)
from domain.errors import DocumentNotFoundError, RagNotFoundError, UnsupportedError
from domain.models import (
    ChunkingConfig,
    Document,
    EmbeddingConfig,
    PreviewChunk,
    Rag,
)
from infrastructure import token_estimation

OPENAI_EMBEDDING = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI, model="text-embedding-3-small"
)
UNPRICED_EMBEDDING = EmbeddingConfig(provider=EmbedderProviderEnum.GEMINI, model="no-such-model-x")
CHUNKING = ChunkingConfig(
    chunk_strategy=ChunkStrategyEnum.CHARACTER,
    chunk_size=50,
    chunk_overlap=0,
    extra={"character": {"regex": r"\n\n"}},
)


def _rag(status: IndexStatusEnum = IndexStatusEnum.NEW) -> Rag:
    return Rag(id=1, status=status, indexing_document_ids=set())


def _document(
    doc_id: int,
    content: bytes = b"alpha beta\n\ngamma delta",
    status: DocumentStatusEnum = DocumentStatusEnum.NEW,
    **kwargs,
) -> Document:
    return Document(
        id=doc_id,
        name=f"doc_{doc_id}.txt",
        content=content,
        config=CHUNKING,
        status=status,
        **kwargs,
    )


class FakeNaiveRepo:
    def __init__(self, documents: list[Document], embedding: EmbeddingConfig = OPENAI_EMBEDDING):
        self.documents = documents
        self.embedding = embedding
        self.writes: list[str] = []

    async def get_rag(self, rag_id: int):
        return _rag()

    async def get_embedding_config(self, rag_id: int):
        return self.embedding

    async def get_documents(self, rag_id: int, ids: frozenset[int]):
        return [d for d in self.documents if d.id in ids]

    async def save_preview_chunks(self, *args, **kwargs):
        self.writes.append("save_preview_chunks")

    async def update_document(self, *args, **kwargs):
        self.writes.append("update_document")


class FakeUoW:
    def __init__(self, naive_rag_repo=None, graph_rag_repo=None):
        self.naive_rag_repo = naive_rag_repo
        self.graph_rag_repo = graph_rag_repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _naive(documents: list[Document], **kwargs) -> tuple[NaiveEstimateOrchestrator, FakeNaiveRepo]:
    repo = FakeNaiveRepo(documents, **kwargs)
    return NaiveEstimateOrchestrator(FakeUoW(naive_rag_repo=repo)), repo


async def test_naive_uses_preview_chunks_when_they_exist():
    document = _document(
        1,
        content=b"never read",
        preview_chunks=[PreviewChunk(text="hello world"), PreviewChunk(text="second chunk here")],
    )
    orchestrator, repo = _naive([document])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    model = "openai/text-embedding-3-small"
    expected_tokens = token_estimation.count_tokens(
        model, "hello world"
    ) + token_estimation.count_tokens(model, "second chunk here")
    assert result.rag_type == RAGStrategy.NAIVE
    assert (result.document_count, result.chunk_count) == (1, 2)
    assert result.embedding.tokens == expected_tokens
    assert result.embedding.exact is True
    assert result.embedding.cost_usd == pytest.approx(expected_tokens * 0.02 / 1_000_000)
    assert repo.writes == []


async def test_naive_chunks_in_memory_without_preview_chunks():
    orchestrator, repo = _naive([_document(1)])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert (result.document_count, result.chunk_count) == (1, 2)
    assert result.embedding.tokens > 0
    assert repo.writes == []


async def test_naive_skips_and_does_not_count_a_document_that_fails_to_chunk(monkeypatch):
    def failing_extractor(extension):
        raise ValueError("corrupt file")

    monkeypatch.setattr(
        "application.orchestrators.estimating.strategies.naive_estimator."
        "build_file_text_extractor",
        failing_extractor,
    )
    good = _document(1, preview_chunks=[PreviewChunk(text="hello world")])
    bad = _document(2)
    orchestrator, _ = _naive([good, bad])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1, 2})))

    assert (result.document_count, result.chunk_count) == (1, 1)


async def test_naive_excludes_unchanged_completed_documents():
    completed = _document(1, status=DocumentStatusEnum.COMPLETED, last_indexing_config=CHUNKING)
    new = _document(2)
    orchestrator, _ = _naive([completed, new])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1, 2})))

    assert result.document_count == 1
    assert result.chunk_count == 2


async def test_naive_includes_completed_document_whose_config_changed():
    changed_config = CHUNKING.model_copy(update={"chunk_size": 999})
    document = _document(
        1,
        status=DocumentStatusEnum.COMPLETED,
        last_indexing_config=changed_config,
        preview_chunks=[PreviewChunk(text="stale preview")],
    )
    orchestrator, _ = _naive([document])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    # Preview chunks are stale once the config changed, so the text is re-chunked.
    assert (result.document_count, result.chunk_count) == (1, 2)


async def test_naive_all_unchanged_completed_documents_estimate_nothing_to_index():
    """The indexer skips every one of them, so the run spends no tokens."""
    documents = [
        _document(1, status=DocumentStatusEnum.COMPLETED, last_indexing_config=CHUNKING),
        _document(2, status=DocumentStatusEnum.COMPLETED, last_indexing_config=CHUNKING),
    ]
    orchestrator, _ = _naive(documents)

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1, 2})))

    assert (result.document_count, result.chunk_count, result.embedding.tokens) == (0, 0, 0)


@pytest.mark.parametrize("status", [DocumentStatusEnum.OUTDATED, DocumentStatusEnum.FAILED])
async def test_naive_counts_outdated_and_failed_documents_even_with_unchanged_config(status):
    """Only a COMPLETED document is skipped; an outdated one is re-embedded."""
    document = _document(1, status=status, last_indexing_config=CHUNKING)
    orchestrator, _ = _naive([document])

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert (result.document_count, result.chunk_count) == (1, 2)
    assert result.embedding.tokens > 0


async def test_naive_unpriced_model_has_null_cost_and_inexact_tokens():
    orchestrator, _ = _naive([_document(1)], embedding=UNPRICED_EMBEDDING)

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert result.embedding.cost_usd is None
    assert result.embedding.exact is False
    assert result.embedding.tokens > 0


async def test_naive_unknown_documents_raise():
    orchestrator, _ = _naive([_document(1)])

    with pytest.raises(DocumentNotFoundError):
        await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({99})))


async def test_naive_unknown_rag_raises():
    orchestrator, repo = _naive([_document(1)])

    async def no_rag(rag_id: int):
        return None

    repo.get_rag = no_rag
    with pytest.raises(RagNotFoundError):
        await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))


def test_build_estimator_supports_only_naive():
    uow = FakeUoW()
    assert isinstance(build_estimator(RAGStrategy.NAIVE, uow), NaiveEstimateOrchestrator)
    with pytest.raises(UnsupportedError):
        build_estimator(RAGStrategy.GRAPH, uow)
    with pytest.raises(UnsupportedError):
        build_estimator("other", uow)


