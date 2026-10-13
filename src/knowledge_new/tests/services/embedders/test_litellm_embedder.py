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


def _response(embeddings: list[list[float]], prompt_tokens: int | None = None):
    usage = None if prompt_tokens is None else type("Usage", (), {"prompt_tokens": prompt_tokens})()
    return type("Resp", (), {"data": [{"embedding": e} for e in embeddings], "usage": usage})()


@pytest.fixture
def config():
    return make_config(EmbedderProviderEnum.OPENAI)


async def test_embed_returns_vector(config):
    with patch.object(
        litellm_embedder.litellm,
        "aembedding",
        AsyncMock(return_value=_response([[0.1, 0.2, 0.3]])),
    ):
        result = await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert result.vector == [0.1, 0.2, 0.3]


async def test_embed_returns_empty_list_when_no_data(config):
    with patch.object(
        litellm_embedder.litellm, "aembedding", AsyncMock(return_value=_response([]))
    ):
        result = await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert result.vector == []


async def test_embed_reports_provider_billed_tokens(config):
    with patch.object(
        litellm_embedder.litellm,
        "aembedding",
        AsyncMock(return_value=_response([[0.1]], prompt_tokens=42)),
    ):
        result = await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert result.tokens == 42


async def test_embed_falls_back_to_local_count_when_provider_reports_no_usage(config):
    with (
        patch.object(
            litellm_embedder.litellm, "aembedding", AsyncMock(return_value=_response([[0.1]]))
        ),
        patch.object(
            litellm_embedder, "count_tokens_batch", AsyncMock(return_value=[7])
        ) as count,
    ):
        result = await LiteLLMEmbedder("sk-test", config).embed("a\nb")

    assert result.tokens == 7
    count.assert_awaited_once_with("openai/m", ["a b"])


async def test_embed_raises_embedding_error_on_client_failure(config):
    with (
        patch.object(
            litellm_embedder.litellm,
            "aembedding",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        pytest.raises(EmbeddingError),
    ):
        await LiteLLMEmbedder("sk-test", config).embed("hi")


async def test_embed_routes_provider_as_custom_llm_provider(config):
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["custom_llm_provider"] == EmbedderProviderEnum.OPENAI
    assert mock.await_args.kwargs["api_key"] == "sk-test"
    assert "input_type" not in mock.await_args.kwargs


async def test_cohere_embedder_sends_search_query_input_type():
    config = make_config(EmbedderProviderEnum.COHERE)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await CohereLiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["input_type"] == "search_query"


async def test_no_endpoint_overrides_sent_when_settings_unset(config, monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert "api_base" not in mock.await_args.kwargs
    assert "extra_headers" not in mock.await_args.kwargs


async def test_custom_base_url_and_headers_sent_to_litellm(config, monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://gateway:8080/v1"
    )
    monkeypatch.setattr(
        litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY"}
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://gateway:8080/v1"
    assert mock.await_args.kwargs["extra_headers"] == {"apikey": "KONG_KEY"}


async def test_custom_base_url_sent_without_headers(config, monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://gateway:8080/v1"
    )
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://gateway:8080/v1"
    assert "extra_headers" not in mock.await_args.kwargs


async def test_custom_headers_sent_without_base_url(config, monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(
        litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY"}
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["extra_headers"] == {"apikey": "KONG_KEY"}
    assert "api_base" not in mock.await_args.kwargs


async def test_endpoint_overrides_apply_to_every_provider(monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://gateway:8080/v1"
    )
    monkeypatch.setattr(
        litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY"}
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await CohereLiteLLMEmbedder(
            "sk-test", make_config(EmbedderProviderEnum.COHERE)
        ).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://gateway:8080/v1"
    assert mock.await_args.kwargs["extra_headers"] == {"apikey": "KONG_KEY"}
    assert mock.await_args.kwargs["input_type"] == "search_query"


def _config_with(**overrides):
    return make_config(EmbedderProviderEnum.OPENAI).model_copy(update=overrides)


async def test_config_headers_sent_without_env_headers(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test", _config_with(extra_headers={"X-Config": "from-config"})
        ).embed("hi")

    assert mock.await_args.kwargs["extra_headers"] == {"X-Config": "from-config"}


async def test_config_headers_merge_with_env_headers_and_win_on_collision(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(
        litellm_embedder.settings,
        "EMBEDDING_HEADERS",
        {"apikey": "ENV_KEY", "X-Env-Only": "env"},
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test",
            _config_with(extra_headers={"apikey": "CONFIG_KEY", "X-Config": "config"}),
        ).embed("hi")

    assert mock.await_args.kwargs["extra_headers"] == {
        "apikey": "CONFIG_KEY",
        "X-Env-Only": "env",
        "X-Config": "config",
    }


async def test_config_base_url_wins_over_env_base_url(monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://env-gateway:8080/v1"
    )
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test", _config_with(base_url="http://config-gateway:9090/v1")
        ).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://config-gateway:9090/v1"


async def test_env_base_url_used_when_config_has_none(monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://env-gateway:8080/v1"
    )
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder("sk-test", _config_with(base_url=None)).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://env-gateway:8080/v1"


async def test_config_base_url_sent_without_env_settings(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test", _config_with(base_url="http://config-gateway:9090/v1")
        ).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://config-gateway:9090/v1"
    assert "extra_headers" not in mock.await_args.kwargs


async def test_cohere_embedder_keeps_input_type_with_config_overrides(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", None)
    config = make_config(EmbedderProviderEnum.COHERE).model_copy(
        update={"base_url": "http://cohere-gateway/v1", "extra_headers": {"X-Config": "c"}}
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await CohereLiteLLMEmbedder("sk-test", config).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "http://cohere-gateway/v1"
    assert mock.await_args.kwargs["extra_headers"] == {"X-Config": "c"}
    assert mock.await_args.kwargs["input_type"] == "search_query"


async def test_config_header_replaces_env_header_differing_only_in_case(monkeypatch):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(
        litellm_embedder.settings,
        "EMBEDDING_HEADERS",
        {"apikey": "ENV_KEY", "X-Env-Only": "env"},
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test", _config_with(extra_headers={"ApiKey": "CONFIG_KEY"})
        ).embed("hi")

    assert mock.await_args.kwargs["extra_headers"] == {
        "X-Env-Only": "env",
        "ApiKey": "CONFIG_KEY",
    }


async def test_env_headers_are_not_sent_to_a_config_base_url(monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://env-gateway:8080/v1"
    )
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY"})
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test",
            _config_with(
                base_url="https://attacker.example/v1", extra_headers={"X-Config": "c"}
            ),
        ).embed("hi")

    assert mock.await_args.kwargs["api_base"] == "https://attacker.example/v1"
    assert mock.await_args.kwargs["extra_headers"] == {"X-Config": "c"}


async def test_env_headers_are_not_sent_to_a_config_base_url_without_env_base_url(
    monkeypatch,
):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY"})
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test", _config_with(base_url="https://attacker.example/v1")
        ).embed("hi")

    assert "extra_headers" not in mock.await_args.kwargs


async def test_env_headers_merge_when_config_base_url_is_the_env_url(monkeypatch):
    monkeypatch.setattr(
        litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", "http://env-gateway:8080/v1"
    )
    monkeypatch.setattr(
        litellm_embedder.settings, "EMBEDDING_HEADERS", {"apikey": "KONG_KEY", "X-Env": "e"}
    )
    mock = AsyncMock(return_value=_response([[0.1]]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        await LiteLLMEmbedder(
            "sk-test",
            _config_with(
                base_url="http://env-gateway:8080/v1/", extra_headers={"ApiKey": "CONFIG_KEY"}
            ),
        ).embed("hi")

    assert mock.await_args.kwargs["extra_headers"] == {"X-Env": "e", "ApiKey": "CONFIG_KEY"}
