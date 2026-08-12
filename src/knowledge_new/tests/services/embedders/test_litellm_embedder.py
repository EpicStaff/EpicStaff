from unittest.mock import AsyncMock, patch

import pytest
from domain.enums import EmbedderProviderEnum
from domain.errors import EmbeddingError
from infrastructure.naive.embedders.strategies import litellm_embedder
from infrastructure.naive.embedders.strategies.litellm_embedder import (
    CohereLiteLLMEmbedder,
    LiteLLMEmbedder,
)
from tests.services.embedders.conftest import make_config


def _response(embeddings: list[list[float]]):
    return type("Resp", (), {"data": [{"embedding": e} for e in embeddings]})()


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.OPENAI)


async def test_embed_returns_vector(config):
    with patch.object(
        litellm_embedder.litellm,
        "aembedding",
        AsyncMock(return_value=_response([[0.1, 0.2, 0.3]])),
    ):
        result = await LiteLLMEmbedder(config).embed("hi")

    assert result == [0.1, 0.2, 0.3]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(
        litellm_embedder.litellm, "aembedding", AsyncMock(return_value=_response([]))
    ):
        result = await LiteLLMEmbedder(config).embed("hi")

    assert result == []


async def test_embed_raises_embedding_error_on_client_failure(config):
    with (
        patch.object(
            litellm_embedder.litellm,
            "aembedding",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        pytest.raises(EmbeddingError),
    ):
        await LiteLLMEmbedder(config).embed("hi")


async def test_embed_routes_provider_as_custom_llm_provider(config):
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(config).embed("hi")

    assert mock.await_args.kwargs["custom_llm_provider"] == EmbedderProviderEnum.OPENAI
    assert "input_type" not in mock.await_args.kwargs


async def test_cohere_embedder_sends_search_query_input_type():
    config = make_config(EmbedderProviderEnum.COHERE)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await CohereLiteLLMEmbedder(config).embed("hi")

    assert mock.await_args.kwargs["input_type"] == "search_query"
