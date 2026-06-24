from unittest.mock import AsyncMock, Mock, patch

import pytest

from enums import (
    DocumentStatusEnum,
    DocumentErrorCode,
    EmbedderProviderEnum,
    IndexStatusEnum,
    RAGStrategy,
)
from errors import EmbeddingError, EmbedderUnavailableError, NoDocumentsToIndexError
from models import EmbeddingConfig, IndexRequest, PreviewChunk
from orchestrators.indexing.strategies import naive_indexer
from orchestrators.indexing.strategies.naive_indexer import NaiveIndexer

from tests.orchestrators.indexing.conftest import FakeUoW, make_document


_REQUEST = IndexRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE)
_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI,
    api_key="k",
    model="m",
)
_VECTOR = [0.1, 0.2]


def _embedder_mock(embed_result=None) -> Mock:
    mock = Mock()
    if embed_result is None:
        mock.embed = AsyncMock(return_value=_VECTOR)
    else:
        mock.embed = embed_result
    return mock


def _chunker_mock(chunks: list[PreviewChunk] | None = None) -> Mock:
    mock = Mock()
    mock.chunk = AsyncMock(return_value=chunks or [PreviewChunk(text="a")])
    return mock


def _extractor_mock(text: str = "t") -> Mock:
    mock = Mock()
    mock.extract = AsyncMock(return_value=text)
    return mock


async def test_no_embedding_config_raises():
    uow = FakeUoW(embedding_config=None, documents=[])

    with pytest.raises(EmbedderUnavailableError):
        await NaiveIndexer().index(_REQUEST, uow)


async def test_all_documents_succeed_marks_completed():
    doc1 = make_document(doc_id=1)
    doc2 = make_document(doc_id=2)
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc1, doc2])
    extractor = _extractor_mock()
    chunker = _chunker_mock()
    embedder = _embedder_mock()

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    assert doc1.status == DocumentStatusEnum.COMPLETED
    assert doc2.status == DocumentStatusEnum.COMPLETED
    assert uow.naive_rag_repo.save_indexed_chunks.await_count == 2
    assert extractor.extract.await_count == 2

    assert (
        uow.naive_rag_repo.update_rag_status.await_args_list[0].kwargs["status"]
        == IndexStatusEnum.PROCESSING
    )
    uow.naive_rag_repo.update_rag_status.assert_awaited_with(
        rag_id=_REQUEST.rag_id,
        status=IndexStatusEnum.COMPLETED,
    )

    assert doc1.indexed_chunks[0].vector == _VECTOR
    assert doc1.indexed_chunks[0].text == "a"


async def test_reuses_existing_preview_chunks():
    doc = make_document(doc_id=1, with_preview=True)
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc])
    extractor = _extractor_mock()
    chunker = _chunker_mock()
    embedder = _embedder_mock()

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    extractor.extract.assert_not_awaited()
    chunker.chunk.assert_not_awaited()

    assert embedder.embed.await_count == 1
    assert doc.status == DocumentStatusEnum.COMPLETED
    uow.naive_rag_repo.save_indexed_chunks.assert_awaited_once()


async def test_mixed_results_marks_warning():
    doc1 = make_document(doc_id=1)
    doc2 = make_document(doc_id=2)
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc1, doc2])
    extractor = _extractor_mock()
    chunker = _chunker_mock()
    embed_mock = AsyncMock(side_effect=[_VECTOR, EmbeddingError("t", Mock())])
    embedder = _embedder_mock(embed_result=embed_mock)

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    assert doc1.status == DocumentStatusEnum.COMPLETED
    assert doc2.status == DocumentStatusEnum.FAILED

    uow.naive_rag_repo.save_indexed_chunks.assert_awaited_once()

    uow.naive_rag_repo.update_rag_status.assert_awaited_with(
        rag_id=_REQUEST.rag_id,
        status=IndexStatusEnum.WARNING,
    )


async def test_all_documents_fail_marks_failed():
    doc = make_document(doc_id=1)
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc])
    extractor = _extractor_mock()
    chunker = _chunker_mock()
    embed_mock = AsyncMock(side_effect=EmbeddingError("t", Mock()))
    embedder = _embedder_mock(embed_result=embed_mock)

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    assert doc.status == DocumentStatusEnum.FAILED
    uow.naive_rag_repo.save_indexed_chunks.assert_not_awaited()
    uow.naive_rag_repo.update_rag_status.assert_awaited_with(
        rag_id=_REQUEST.rag_id,
        status=IndexStatusEnum.FAILED,
    )


async def test_no_documents_raises():
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[])

    with patch.object(naive_indexer, "build_embedder", return_value=_embedder_mock()):
        with pytest.raises(NoDocumentsToIndexError):
            await NaiveIndexer().index(_REQUEST, uow)

    uow.naive_rag_repo.update_document.assert_not_awaited()
    uow.naive_rag_repo.save_indexed_chunks.assert_not_awaited()
    uow.naive_rag_repo.update_rag_status.assert_not_awaited()


async def test_already_indexed_document_is_skipped_keeps_completed():
    doc = make_document(doc_id=1)
    doc.status = DocumentStatusEnum.COMPLETED
    doc.last_indexing_config = doc.config
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc])
    extractor = _extractor_mock()
    chunker = _chunker_mock()
    embedder = _embedder_mock()

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    assert doc.status == DocumentStatusEnum.COMPLETED
    extractor.extract.assert_not_awaited()
    embedder.embed.assert_not_awaited()
    uow.naive_rag_repo.save_indexed_chunks.assert_not_awaited()
    uow.naive_rag_repo.update_rag_status.assert_awaited_with(
        rag_id=_REQUEST.rag_id,
        status=IndexStatusEnum.COMPLETED,
    )


async def test_document_with_no_chunks_marks_failed():
    doc = make_document(doc_id=1)
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, documents=[doc])
    extractor = _extractor_mock()
    chunker = Mock()
    chunker.chunk = AsyncMock(return_value=[])
    embedder = _embedder_mock()

    with (
        patch.object(naive_indexer, "build_embedder", return_value=embedder),
        patch.object(naive_indexer, "build_chunker", return_value=chunker),
        patch.object(
            naive_indexer, "build_file_text_extractor", return_value=extractor
        ),
    ):
        await NaiveIndexer().index(_REQUEST, uow)

    assert doc.status == DocumentStatusEnum.FAILED
    assert doc.error_code == DocumentErrorCode.NO_CHUNKS_PRODUCED
    embedder.embed.assert_not_awaited()
    uow.naive_rag_repo.save_indexed_chunks.assert_not_awaited()
    uow.naive_rag_repo.update_rag_status.assert_awaited_with(
        rag_id=_REQUEST.rag_id,
        status=IndexStatusEnum.FAILED,
    )
