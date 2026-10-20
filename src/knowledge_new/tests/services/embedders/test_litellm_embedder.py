from unittest.mock import AsyncMock, patch

import pytest
from domain.enums import EmbedderProviderEnum
from domain.errors import EmbeddingError
from infrastructure.naive.embedders import build_embedder
from infrastructure.naive.embedders.strategies import litellm_embedder
from tests.services.embedders.conftest import make_config


def _response(embeddings: list[list[float]]):
    return type("Resp", (), {"data": [{"embedding": e} for e in embeddings]})()


@pytest.fixture
def litellm_api():
    """litellm's embedding call, the boundary to the provider's HTTP API."""
    mock = AsyncMock(return_value=_response([[0.1, 0.2, 0.3]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        yield mock


@pytest.fixture
def no_endpoint_overrides(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)


def _embedder(provider: EmbedderProviderEnum = EmbedderProviderEnum.OPENAI):
    return build_embedder(provider, "sk-test", make_config(provider))


async def test_embed_sends_one_line_text_to_the_provider_and_returns_its_vector(
    litellm_api, no_endpoint_overrides
):
    result = await _embedder().embed("hello\nworld")

    assert result == [0.1, 0.2, 0.3]
    request = litellm_api.await_args.kwargs
    assert request == {
        "input": ["hello world"],
        "api_key": "sk-test",
        "model": "m",
        "custom_llm_provider": EmbedderProviderEnum.OPENAI,
    }


async def test_embed_returns_empty_list_when_provider_returns_no_data(litellm_api):
    litellm_api.return_value = _response([])

    assert await _embedder().embed("hi") == []


async def test_provider_failure_raises_embedding_error(litellm_api):
    litellm_api.side_effect = RuntimeError("boom")

    with pytest.raises(EmbeddingError):
        await _embedder().embed("hi")


async def test_cohere_queries_are_embedded_as_search_queries(litellm_api, no_endpoint_overrides):
    """Cohere v3 defaults to `search_document`; queries must say they are queries."""
    await _embedder(EmbedderProviderEnum.COHERE).embed("hi")

    assert litellm_api.await_args.kwargs["input_type"] == "search_query"


@pytest.mark.parametrize("provider", [EmbedderProviderEnum.OPENAI, EmbedderProviderEnum.COHERE])
@pytest.mark.parametrize(
    ("base_url", "headers"),
    [
        ("http://gateway:8080/v1", {"apikey": "KONG_KEY"}),
        ("http://gateway:8080/v1", None),
        (None, {"apikey": "KONG_KEY"}),
    ],
    ids=["base-url-and-headers", "base-url-only", "headers-only"],
)
async def test_deployment_endpoint_overrides_reach_every_provider(
    litellm_api, monkeypatch, provider, base_url, headers
):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", base_url)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", headers)

    await _embedder(provider).embed("hi")

    request = litellm_api.await_args.kwargs
    assert request.get("api_base") == base_url
    assert request.get("extra_headers") == headers
