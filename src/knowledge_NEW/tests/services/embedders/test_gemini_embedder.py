import pytest
from unittest.mock import patch, AsyncMock, Mock

from enums import EmbedderProviderEnum
from errors import EmbeddingError
from services.embedders.strategies import gemini_embedder
from services.embedders.strategies.gemini_embedder import GeminiEmbedder

from tests.services.embedders.conftest import make_config


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.GEMINI)


async def test_embed_returns_vector(config):
    with patch.object(gemini_embedder.genai, "Client") as MockClient:
        client = MockClient.return_value
        client.aio.models.embed_content = AsyncMock(
            return_value=Mock(embeddings=[Mock(values=[0.1, 0.2])])
        )
        embedder = GeminiEmbedder(config)
        result = await embedder.embed("hi")

    assert result == [0.1, 0.2]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(gemini_embedder.genai, "Client") as MockClient:
        client = MockClient.return_value
        client.aio.models.embed_content = AsyncMock(return_value=Mock(embeddings=[]))
        embedder = GeminiEmbedder(config)
        result = await embedder.embed("hi")

    assert result == []


async def test_embed_raises_embedding_error_on_client_failure(config):
    with patch.object(gemini_embedder.genai, "Client") as MockClient:
        client = MockClient.return_value
        client.aio.models.embed_content = AsyncMock(side_effect=RuntimeError("boom"))
        embedder = GeminiEmbedder(config)

        with pytest.raises(EmbeddingError):
            await embedder.embed("hi")
