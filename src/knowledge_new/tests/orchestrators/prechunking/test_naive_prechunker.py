import asyncio

import pytest
from enums import ChunkStrategyEnum, DocumentStatusEnum, RAGStrategy
from errors import ChunkingError, FileTextExtractingError, NoPreviewChunksProducedError
from models import (
    ChunkingConfig,
    Document,
    PrechunkRequest,
    PrechunkResponse,
    PreviewChunk,
)
from orchestrators.prechunking.strategies.naive_prechunker import NaivePrechunker


class FakeNaiveRagRepo:
    """In-memory repo implementing the AbstractNaiveRagRepository behavior we exercise.

    status_log records document.status at each update_document call, so tests can
    assert the order of status transitions. get_document_raises lets a test inject
    a failure at the preparation stage.
    """

    def __init__(
        self, document: Document, *, get_document_raises: BaseException | None = None
    ):
        self._document = document
        self._get_document_raises = get_document_raises
        self.status_log: list[DocumentStatusEnum] = []
        self.save_chunks_calls: list[tuple[int, list[PreviewChunk]]] = []

    async def get_document(self, rag_id: int, document_id: int) -> Document | None:
        if self._get_document_raises is not None:
            raise self._get_document_raises
        return self._document

    async def update_document(self, rag_id: int, document: Document) -> None:
        self.status_log.append(document.status)

    async def save_preview_chunks(
        self, document_id: int, chunks: list[PreviewChunk]
    ) -> None:
        self.save_chunks_calls.append((document_id, list(chunks)))


class FakeUoW:
    """In-memory unit of work — async context manager over a FakeNaiveRagRepo.

    commit_errors is consumed one entry per commit() call: a non-None entry is
    raised, letting a test inject a failure at a specific persistence step.
    """

    def __init__(
        self,
        document: Document,
        *,
        get_document_raises: BaseException | None = None,
        commit_errors: list[BaseException] | None = None,
    ):
        self.naive_rag_repo = FakeNaiveRagRepo(
            document, get_document_raises=get_document_raises
        )
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


async def test_already_chunked_same_config_short_circuits_without_status_changes():
    existing_chunks = [PreviewChunk(text="alpha"), PreviewChunk(text="beta")]
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
        status=DocumentStatusEnum.CHUNKED,
        config=config,
        last_indexing_config=config,  # indexed with the same config → no reindex needed
        preview_chunks=existing_chunks,
    )
    request = PrechunkRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE, document_id=7)
    uow = FakeUoW(document)

    response = await NaivePrechunker(uow).execute(request)

    assert response == PrechunkResponse(
        request=request, status=DocumentStatusEnum.CHUNKED, chunks=existing_chunks
    )
    assert response.chunks == existing_chunks  # old chunks returned unchanged
    assert uow.naive_rag_repo.status_log == []  # no CHUNKING/CHUNKED transitions
    assert uow.naive_rag_repo.save_chunks_calls == []
    assert document.status == DocumentStatusEnum.CHUNKED


async def test_already_chunked_different_config_rechunks_and_replaces_preview():
    old_chunks = [PreviewChunk(text="alphabeta")]
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
        status=DocumentStatusEnum.CHUNKED,
        config=current_config,
        last_indexing_config=previous_config,  # differs from config → reindex required
        preview_chunks=old_chunks,
    )
    request = PrechunkRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE, document_id=7)
    uow = FakeUoW(document)

    response = await NaivePrechunker(uow).execute(request)

    new_chunks = [PreviewChunk(text="alpha"), PreviewChunk(text="beta")]
    assert response == PrechunkResponse(
        request=request, status=DocumentStatusEnum.CHUNKED, chunks=new_chunks
    )
    assert response.chunks != old_chunks  # response differs from the stale preview
    assert document.preview_chunks == new_chunks  # old preview replaced by new
    # prechunker sets preview_chunks and calls _update_document once without changing status
    assert uow.naive_rag_repo.status_log == [DocumentStatusEnum.CHUNKED]
    assert document.status == DocumentStatusEnum.CHUNKED


@pytest.mark.parametrize(
    "uow_kwargs,expected_status_log,expected_final_status",
    [
        # cancelling in preparation: document never fetched → on_cancel is a no-op
        (
            {"get_document_raises": asyncio.CancelledError()},
            [],
            DocumentStatusEnum.NEW,
        ),
        # cancelling during the single _update_document commit: update_document logged NEW,
        # then commit raises; on_cancel condition (NEW not in {CHUNKED, NEW}) is False → no restore
        (
            {"commit_errors": [asyncio.CancelledError()]},
            [DocumentStatusEnum.NEW],
            DocumentStatusEnum.NEW,
        ),
    ],
    ids=["preparation", "during_commit"],
)
async def test_cancellation_restores_status_per_stage(
    uow_kwargs,
    expected_status_log,
    expected_final_status,
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
    )
    request = PrechunkRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE, document_id=7)
    uow = FakeUoW(document, **uow_kwargs)

    result = await NaivePrechunker(uow).execute(request)

    assert result is None  # execute swallows CancelledError, returns None
    assert uow.naive_rag_repo.status_log == expected_status_log
    assert document.status == expected_final_status


@pytest.mark.parametrize(
    "name,content,config_kwargs,expected_exc",
    [
        (
            "doc.csv",
            b"\xff\xfe",
            {
                "chunk_strategy": ChunkStrategyEnum.CSV,
                "chunk_size": 50,
                "chunk_overlap": 0,
            },
            FileTextExtractingError,
        ),
        (
            "doc.txt",
            b"some valid text",
            {
                "chunk_strategy": ChunkStrategyEnum.CHARACTER,
                "chunk_size": 50,
                "chunk_overlap": 0,
                "extra": {"character": {"regex": "["}},
            },
            ChunkingError,
        ),
        (
            "doc.txt",
            b"\n\n",
            {
                "chunk_strategy": ChunkStrategyEnum.CHARACTER,
                "chunk_size": 50,
                "chunk_overlap": 0,
                "extra": {"character": {"regex": r"\n\n"}},
            },
            NoPreviewChunksProducedError,
        ),
    ],
    ids=["extraction_failure", "chunking_failure", "no_chunks_produced"],
)
async def test_error_marks_document_failed_per_stage(
    name,
    content,
    config_kwargs,
    expected_exc,
):
    document = Document(
        id=7,
        name=name,
        content=content,
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(**config_kwargs),
    )
    request = PrechunkRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE, document_id=7)
    uow = FakeUoW(document)

    with pytest.raises(expected_exc):
        await NaivePrechunker(uow).execute(request)

    assert document.status == DocumentStatusEnum.FAILED
    assert document.error_message  # populated by mark_as_failed(error)
    assert uow.naive_rag_repo.status_log == [DocumentStatusEnum.FAILED]
