import pytest
from unittest.mock import patch, AsyncMock, Mock

from cohere import EmbeddingsFloatsEmbedResponse

from enums import EmbedderProviderEnum
from errors import EmbeddingError
from services.embedders.strategies import cohere_embedder
from services.embedders.strategies.cohere_embedder import CohereEmbedder

from tests.services.embedders.conftest import make_config


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.COHERE)


async def test_embed_returns_vector(config):
    with patch.object(cohere_embedder, "AsyncClient") as MockAsyncClient:
        client = MockAsyncClient.return_value
        response = Mock(spec=EmbeddingsFloatsEmbedResponse)
        response.embeddings = [[0.4, 0.5]]
        client.embed = AsyncMock(return_value=response)
        embedder = CohereEmbedder(config)
        result = await embedder.embed("hi")

    assert result == [0.4, 0.5]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(cohere_embedder, "AsyncClient") as MockAsyncClient:
        client = MockAsyncClient.return_value
        response = Mock(spec=EmbeddingsFloatsEmbedResponse)
        response.embeddings = []
        client.embed = AsyncMock(return_value=response)
        embedder = CohereEmbedder(config)
        result = await embedder.embed("hi")

    assert result == []


async def test_embed_raises_embedding_error_on_client_failure(config):
    with patch.object(cohere_embedder, "AsyncClient") as MockAsyncClient:
        client = MockAsyncClient.return_value
        client.embed = AsyncMock(side_effect=RuntimeError("boom"))
        embedder = CohereEmbedder(config)

        with pytest.raises(EmbeddingError):
            await embedder.embed("hi")
