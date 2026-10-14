from unittest.mock import AsyncMock, patch

import pytest
from domain.enums import EmbedderProviderEnum
from domain.errors import EmbeddingError
from infrastructure.naive.embedders import build_embedder
from infrastructure.naive.embedders.strategies import litellm_embedder
from tests.services.embedders.conftest import make_config


def _response(embeddings: list[list[float]], prompt_tokens: int | None = None):
    usage = None if prompt_tokens is None else type("Usage", (), {"prompt_tokens": prompt_tokens})()
    return type("Resp", (), {"data": [{"embedding": e} for e in embeddings], "usage": usage})()


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


def _embedder(provider: EmbedderProviderEnum = EmbedderProviderEnum.OPENAI, **config_overrides):
    config = make_config(provider).model_copy(update=config_overrides)
    return build_embedder(provider, "sk-test", config)


async def test_embed_sends_one_line_text_to_the_provider_and_returns_its_vector(
    litellm_api, no_endpoint_overrides
):
    result = await _embedder().embed("hello\nworld")

    assert result.vector == [0.1, 0.2, 0.3]
    request = litellm_api.await_args.kwargs
    assert request == {
        "input": ["hello world"],
        "api_key": "sk-test",
        "model": "m",
        "custom_llm_provider": EmbedderProviderEnum.OPENAI,
    }


async def test_embed_returns_empty_list_when_provider_returns_no_data(litellm_api):
    litellm_api.return_value = _response([])

    assert (await _embedder().embed("hi")).vector == []


async def test_embed_reports_provider_billed_tokens(litellm_api):
    litellm_api.return_value = _response([[0.1]], prompt_tokens=42)

    result = await _embedder().embed("hi")

    assert result.tokens == 42


async def test_embed_falls_back_to_local_count_when_provider_reports_no_usage(litellm_api):
    with patch.object(
        litellm_embedder, "count_tokens_batch", AsyncMock(return_value=[7])
    ) as count:
        result = await _embedder().embed("a\nb")

    assert result.tokens == 7
    count.assert_awaited_once_with("openai/m", ["a b"])


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


ENV_URL = "http://env-gateway:8080/v1"


def _set_env_endpoint(monkeypatch, base_url, headers):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", base_url)
    monkeypatch.setattr(litellm_embedder.settings, "EMBEDDING_HEADERS", headers)


async def test_config_headers_sent_without_env_headers(litellm_api, no_endpoint_overrides):
    await _embedder(extra_headers={"X-Config": "from-config"}).embed("hi")

    assert litellm_api.await_args.kwargs["extra_headers"] == {"X-Config": "from-config"}


async def test_numeric_env_header_values_are_sent_as_strings(litellm_api, monkeypatch):
    # KNOWLEDGE_EMBEDDING_HEADERS is parsed as JSON, so a value can arrive as a number.
    _set_env_endpoint(monkeypatch, None, {"X-Tenant-Id": 42, "X-Flag": True})

    await _embedder(extra_headers={"X-Config": "c"}).embed("hi")

    sent = litellm_api.await_args.kwargs["extra_headers"]
    assert sent == {"X-Tenant-Id": "42", "X-Flag": "True", "X-Config": "c"}
    assert all(isinstance(value, str) for value in sent.values())


async def test_config_headers_merge_with_env_headers_and_win_on_collision(
    litellm_api, monkeypatch
):
    _set_env_endpoint(monkeypatch, None, {"apikey": "ENV_KEY", "X-Env-Only": "env"})

    await _embedder(extra_headers={"apikey": "CONFIG_KEY", "X-Config": "config"}).embed("hi")

    assert litellm_api.await_args.kwargs["extra_headers"] == {
        "apikey": "CONFIG_KEY",
        "X-Env-Only": "env",
        "X-Config": "config",
    }


async def test_config_base_url_wins_over_env_base_url(litellm_api, monkeypatch):
    _set_env_endpoint(monkeypatch, ENV_URL, None)

    await _embedder(base_url="http://config-gateway:9090/v1").embed("hi")

    assert litellm_api.await_args.kwargs["api_base"] == "http://config-gateway:9090/v1"


async def test_env_base_url_used_when_config_has_none(litellm_api, monkeypatch):
    _set_env_endpoint(monkeypatch, ENV_URL, None)

    await _embedder(base_url=None).embed("hi")

    assert litellm_api.await_args.kwargs["api_base"] == ENV_URL


async def test_config_base_url_sent_without_env_settings(litellm_api, no_endpoint_overrides):
    await _embedder(base_url="http://config-gateway:9090/v1").embed("hi")

    assert litellm_api.await_args.kwargs["api_base"] == "http://config-gateway:9090/v1"
    assert "extra_headers" not in litellm_api.await_args.kwargs


async def test_cohere_embedder_keeps_input_type_with_config_overrides(
    litellm_api, no_endpoint_overrides
):
    await _embedder(
        EmbedderProviderEnum.COHERE,
        base_url="http://cohere-gateway/v1",
        extra_headers={"X-Config": "c"},
    ).embed("hi")

    request = litellm_api.await_args.kwargs
    assert request["api_base"] == "http://cohere-gateway/v1"
    assert request["extra_headers"] == {"X-Config": "c"}
    assert request["input_type"] == "search_query"


async def test_config_header_replaces_env_header_differing_only_in_case(
    litellm_api, monkeypatch
):
    _set_env_endpoint(monkeypatch, None, {"apikey": "ENV_KEY", "X-Env-Only": "env"})

    await _embedder(extra_headers={"ApiKey": "CONFIG_KEY"}).embed("hi")

    assert litellm_api.await_args.kwargs["extra_headers"] == {
        "X-Env-Only": "env",
        "ApiKey": "CONFIG_KEY",
    }


async def test_env_headers_are_not_sent_to_a_config_base_url(litellm_api, monkeypatch):
    _set_env_endpoint(monkeypatch, ENV_URL, {"apikey": "KONG_KEY"})

    await _embedder(
        base_url="https://attacker.example/v1", extra_headers={"X-Config": "c"}
    ).embed("hi")

    request = litellm_api.await_args.kwargs
    assert request["api_base"] == "https://attacker.example/v1"
    assert request["extra_headers"] == {"X-Config": "c"}


async def test_env_headers_are_not_sent_to_a_config_base_url_without_env_base_url(
    litellm_api, monkeypatch
):
    _set_env_endpoint(monkeypatch, None, {"apikey": "KONG_KEY"})

    await _embedder(base_url="https://attacker.example/v1").embed("hi")

    assert "extra_headers" not in litellm_api.await_args.kwargs


async def test_env_headers_merge_when_config_base_url_is_the_env_url(litellm_api, monkeypatch):
    _set_env_endpoint(monkeypatch, ENV_URL, {"apikey": "KONG_KEY", "X-Env": "e"})

    await _embedder(base_url=ENV_URL + "/", extra_headers={"ApiKey": "CONFIG_KEY"}).embed("hi")

    assert litellm_api.await_args.kwargs["extra_headers"] == {
        "X-Env": "e",
        "ApiKey": "CONFIG_KEY",
    }
