from unittest.mock import AsyncMock, Mock, patch

import pytest

from enums import DocumentStatusEnum, RAGStrategy
from errors import ChunkingError, FileTextExtractingError
from models import PreviewChunk, PrechunkRequest, PrechunkResponse
from orchestrators.prechunking.strategies import naive_prechunker
from orchestrators.prechunking.strategies.naive_prechunker import NaivePrechunker

from tests.orchestrators.prechunking.conftest import FakeUoW, make_document


_REQUEST = PrechunkRequest(rag_id=1, rag_strategy=RAGStrategy.NAIVE, document_id=7)
_EXTRACTED_TEXT = "some text"
_PREVIEW_CHUNKS = [PreviewChunk(text="a"), PreviewChunk(text="b")]


def _extractor_mock(return_value: str = _EXTRACTED_TEXT) -> Mock:
    mock = Mock()
    mock.extract = AsyncMock(return_value=return_value)
    return mock


def _chunker_mock(return_value: list[PreviewChunk] = _PREVIEW_CHUNKS) -> Mock:
    mock = Mock()
    mock.chunk = AsyncMock(return_value=return_value)
    return mock


async def test_marks_chunked_and_returns_preview_chunks():
    document = make_document()
    uow = FakeUoW(document)
    extractor = _extractor_mock()
    chunker = _chunker_mock()

    with (
        patch.object(
            naive_prechunker, "build_file_text_extractor", return_value=extractor
        ),
        patch.object(naive_prechunker, "build_chunker", return_value=chunker),
    ):
        response = await NaivePrechunker().chunk(_REQUEST, uow)

    assert response == PrechunkResponse(request=_REQUEST, chunks=_PREVIEW_CHUNKS)
    assert response.chunks == _PREVIEW_CHUNKS
    assert response.request == _REQUEST

    assert document.status == DocumentStatusEnum.CHUNKED

    extractor.extract.assert_awaited_once_with(document.content)
    chunker.chunk.assert_awaited_once_with(_EXTRACTED_TEXT)

    uow.naive_rag_repo.update_document.assert_awaited_once()
    uow.naive_rag_repo.save_preview_chunks.assert_awaited_once_with(
        document_id=document.id,
        chunks=_PREVIEW_CHUNKS,
    )
    uow.commit.assert_awaited_once()


async def test_missing_document_raises():
    uow = FakeUoW(document=None)

    with pytest.raises(Exception):
        await NaivePrechunker().chunk(_REQUEST, uow)


@pytest.mark.parametrize(
    "inject_error",
    ["extractor", "chunker"],
    ids=["FileTextExtractingError", "ChunkingError"],
)
async def test_failure_marks_failed_and_returns_no_chunks(inject_error):
    document = make_document()
    uow = FakeUoW(document)
    extractor = Mock()
    chunker = Mock()

    if inject_error == "extractor":
        extractor.extract = AsyncMock(side_effect=FileTextExtractingError(Mock()))
        chunker.chunk = AsyncMock(return_value=_PREVIEW_CHUNKS)
    else:
        extractor.extract = AsyncMock(return_value=_EXTRACTED_TEXT)
        chunker.chunk = AsyncMock(side_effect=ChunkingError(_EXTRACTED_TEXT, Mock()))

    with (
        patch.object(
            naive_prechunker, "build_file_text_extractor", return_value=extractor
        ),
        patch.object(naive_prechunker, "build_chunker", return_value=chunker),
    ):
        response = await NaivePrechunker().chunk(_REQUEST, uow)

    assert response == PrechunkResponse(request=_REQUEST, chunks=[])
    assert document.status == DocumentStatusEnum.FAILED
    uow.naive_rag_repo.save_preview_chunks.assert_not_called()
    uow.naive_rag_repo.update_document.assert_awaited_once()
    uow.commit.assert_awaited_once()
