from unittest.mock import AsyncMock, Mock, patch

import pytest

from enums import EmbedderProviderEnum
from errors import EmbedderUnavailableError
from models import (
    EmbeddingConfig,
    FoundChunk,
    NaiveSearchConfig,
    SearchRequest,
)
from orchestrators.searching.strategies import naive_search
from orchestrators.searching.strategies.naive_search import NaiveSearch

from tests.orchestrators.searching.conftest import FakeUoW


_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI,
    api_key="k",
    model="m",
)
_VECTOR = [0.1, 0.2]
_CHUNKS = [FoundChunk(order=0, similarity=0.9, text="hit", source="doc")]
_REQUEST = SearchRequest(
    rag_id=1,
    query="hello",
    search_config=NaiveSearchConfig(search_limit=5, similarity_threshold=0.3),
)


def _embedder_mock() -> Mock:
    mock = Mock()
    mock.embed = AsyncMock(return_value=_VECTOR)
    return mock


async def test_returns_matching_chunks():
    uow = FakeUoW(embedding_config=_EMBEDDING_CONFIG, chunks=_CHUNKS)
    embedder = _embedder_mock()

    with patch.object(naive_search, "build_embedder", return_value=embedder):
        response = await NaiveSearch().search(_REQUEST, uow)

    assert response.request == _REQUEST
    assert response.chunks == _CHUNKS
    embedder.embed.assert_awaited_once_with(_REQUEST.query)
    uow.naive_rag_repo.search_chunks.assert_awaited_once_with(
        rag_id=_REQUEST.rag_id,
        vector=_VECTOR,
        limit=5,
        similarity_threshold=0.3,
    )


async def test_no_embedding_config_raises():
    uow = FakeUoW(embedding_config=None, chunks=[])

    with pytest.raises(EmbedderUnavailableError):
        await NaiveSearch().search(_REQUEST, uow)
