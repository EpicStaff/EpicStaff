from unittest.mock import AsyncMock, Mock, patch

import pytest
from enums import EmbedderProviderEnum
from errors import EmbeddingError
from services.embedders.strategies import together_ai_embedder
from services.embedders.strategies.together_ai_embedder import TogetherAIEmbedder
from tests.services.embedders.conftest import make_config


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.TOGETHER_AI)


async def test_embed_returns_vector(config):
    with patch.object(together_ai_embedder, "AsyncTogether") as mock_async_together:
        client = mock_async_together.return_value
        client.embeddings.create = AsyncMock(
            return_value=Mock(data=[Mock(embedding=[0.1, 0.2, 0.3])])
        )
        embedder = TogetherAIEmbedder(config)
        result = await embedder.embed("hi")

    assert result == [0.1, 0.2, 0.3]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(together_ai_embedder, "AsyncTogether") as mock_async_together:
        client = mock_async_together.return_value
        client.embeddings.create = AsyncMock(return_value=Mock(data=[]))
        embedder = TogetherAIEmbedder(config)
        result = await embedder.embed("hi")

    assert result == []


async def test_embed_raises_embedding_error_on_client_failure(config):
    with patch.object(together_ai_embedder, "AsyncTogether") as mock_async_together:
        client = mock_async_together.return_value
        client.embeddings.create = AsyncMock(side_effect=RuntimeError("boom"))
        embedder = TogetherAIEmbedder(config)

        with pytest.raises(EmbeddingError):
            await embedder.embed("hi")
