import pytest
from application.commands import GetIndexEstimate
from application.orchestrators.estimating import build_estimator
from application.orchestrators.estimating.strategies import (
    GraphEstimateOrchestrator,
    NaiveEstimateOrchestrator,
)
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
    GraphEstimateConfig,
    GraphEstimateOverrides,
    PreviewChunk,
    Rag,
)
from graphrag_input import TextDocument
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


class FakeGraphRepo:
    def __init__(self, documents: list[TextDocument], config: GraphEstimateConfig, rag: Rag):
        self.documents = documents
        self.config = config
        self.rag = rag

    async def get_rag(self, rag_id: int):
        return self.rag

    async def get_estimate_config(self, rag_id: int):
        return self.config

    async def get_documents(self, rag_id: int, ids: frozenset[int]):
        return [d for d in self.documents if int(d.id) in ids]

    async def get_indexed_documents_excluding(self, rag_id: int, ids: frozenset[int]):
        return [
            d
            for d in self.documents
            if int(d.id) not in ids and d.raw_data["status"] == DocumentStatusEnum.COMPLETED
        ]


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


def _graph_config(**overrides) -> GraphEstimateConfig:
    values = dict(
        embedding=OPENAI_EMBEDDING,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        chunk_size=100,
        chunk_overlap=10,
        max_gleanings=1,
    )
    return GraphEstimateConfig(**{**values, **overrides})


def _text_document(doc_id: int, text: str, status: str = "new") -> TextDocument:
    return TextDocument(
        id=str(doc_id),
        text=text,
        title=f"doc_{doc_id}.txt",
        creation_date="2024-01-01T00:00:00",
        raw_data={"status": status},
    )


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
    assert result.llm is None
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


async def test_graph_returns_llm_block_with_custom_prices():
    text = "word " * 500
    config = _graph_config(input_cost_per_token=0.001, output_cost_per_token=0.002)
    repo = FakeGraphRepo([_text_document(1, text)], config, _rag())
    orchestrator = GraphEstimateOrchestrator(FakeUoW(graph_rag_repo=repo))

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert result.rag_type == RAGStrategy.GRAPH
    assert result.document_count == 1
    assert result.chunk_count > 1
    assert result.llm.calls == result.chunk_count * 2
    assert result.llm.tokens_max == result.llm.tokens_min * 2
    assert result.llm.tokens_min > result.embedding.tokens
    assert result.llm.cost_usd_max == pytest.approx(result.llm.cost_usd_min * 2)
    assert result.llm.cost_usd_min > 0


async def test_graph_index_config_overrides_apply_on_top_of_stored_config():
    text = "word " * 500
    stored = _graph_config(chunk_size=200, chunk_overlap=10, max_gleanings=0)
    repo = FakeGraphRepo([_text_document(1, text)], stored, _rag())
    orchestrator = GraphEstimateOrchestrator(FakeUoW(graph_rag_repo=repo))
    document_ids = frozenset({1})

    baseline = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=document_ids))
    overridden = await orchestrator.execute(
        GetIndexEstimate(
            rag_id=1,
            document_ids=document_ids,
            index_config=GraphEstimateOverrides(chunk_size=50, max_gleanings=2),
        )
    )

    assert overridden.chunk_count > baseline.chunk_count
    assert baseline.llm.calls == baseline.chunk_count
    assert overridden.llm.calls == overridden.chunk_count * 3
    assert repo.config == stored


def test_graph_estimate_overrides_leave_unset_fields_alone():
    config = _graph_config(chunk_size=100, chunk_overlap=10, max_gleanings=1)

    applied = GraphEstimateOverrides(chunk_overlap=20).apply_to(config)

    assert (applied.chunk_size, applied.chunk_overlap, applied.max_gleanings) == (100, 20, 1)


async def test_naive_ignores_index_config_overrides():
    orchestrator, _ = _naive([_document(1)])
    document_ids = frozenset({1})

    plain = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=document_ids))
    with_overrides = await orchestrator.execute(
        GetIndexEstimate(
            rag_id=1,
            document_ids=document_ids,
            index_config=GraphEstimateOverrides(chunk_size=5),
        )
    )

    assert with_overrides == plain


async def test_graph_llm_cost_is_null_for_unpriced_model_without_custom_prices():
    config = _graph_config(llm_model="no-such-model-x")
    repo = FakeGraphRepo([_text_document(1, "short text")], config, _rag())
    orchestrator = GraphEstimateOrchestrator(FakeUoW(graph_rag_repo=repo))

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert result.llm.cost_usd_min is None
    assert result.llm.cost_usd_max is None
    assert result.llm.calls == 2


async def test_graph_reindex_of_completed_index_includes_other_completed_documents():
    documents = [
        _text_document(1, "alpha beta", status=DocumentStatusEnum.COMPLETED),
        _text_document(2, "gamma delta", status=DocumentStatusEnum.COMPLETED),
        _text_document(3, "epsilon", status=DocumentStatusEnum.NEW),
    ]
    repo = FakeGraphRepo(documents, _graph_config(), _rag(IndexStatusEnum.COMPLETED))
    orchestrator = GraphEstimateOrchestrator(FakeUoW(graph_rag_repo=repo))

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({1})))

    assert result.document_count == 2


async def test_graph_update_run_counts_only_selected_new_documents():
    documents = [
        _text_document(1, "alpha beta", status=DocumentStatusEnum.COMPLETED),
        _text_document(3, "epsilon", status=DocumentStatusEnum.NEW),
    ]
    repo = FakeGraphRepo(documents, _graph_config(), _rag(IndexStatusEnum.COMPLETED))
    orchestrator = GraphEstimateOrchestrator(FakeUoW(graph_rag_repo=repo))

    result = await orchestrator.execute(GetIndexEstimate(rag_id=1, document_ids=frozenset({3})))

    assert result.document_count == 1


def test_build_estimator_registers_both_strategies():
    uow = FakeUoW()
    assert isinstance(build_estimator(RAGStrategy.NAIVE, uow), NaiveEstimateOrchestrator)
    assert isinstance(build_estimator(RAGStrategy.GRAPH, uow), GraphEstimateOrchestrator)
    with pytest.raises(UnsupportedError):
        build_estimator("other", uow)
