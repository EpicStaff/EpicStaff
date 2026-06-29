import pytest
from unittest.mock import patch, AsyncMock, Mock

from enums import EmbedderProviderEnum
from errors import EmbeddingError
from services.embedders.strategies import openai_embedder
from services.embedders.strategies.openai_embedder import OpenAIEmbedder

from tests.services.embedders.conftest import make_config


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.OPENAI)


async def test_embed_returns_vector(config):
    with patch.object(openai_embedder, "AsyncOpenAI") as MockAsyncOpenAI:
        client = MockAsyncOpenAI.return_value
        client.embeddings.create = AsyncMock(
            return_value=Mock(data=[Mock(embedding=[0.1, 0.2, 0.3])])
        )
        embedder = OpenAIEmbedder(config)
        result = await embedder.embed("hi")

    assert result == [0.1, 0.2, 0.3]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(openai_embedder, "AsyncOpenAI") as MockAsyncOpenAI:
        client = MockAsyncOpenAI.return_value
        client.embeddings.create = AsyncMock(return_value=Mock(data=[]))
        embedder = OpenAIEmbedder(config)
        result = await embedder.embed("hi")

    assert result == []


async def test_embed_raises_embedding_error_on_client_failure(config):
    with patch.object(openai_embedder, "AsyncOpenAI") as MockAsyncOpenAI:
        client = MockAsyncOpenAI.return_value
        client.embeddings.create = AsyncMock(side_effect=RuntimeError("boom"))
        embedder = OpenAIEmbedder(config)

        with pytest.raises(EmbeddingError):
            await embedder.embed("hi")
