from unittest.mock import AsyncMock, patch

import pytest
from application.commands import RunSearch
from application.orchestrators.searching.strategies import naive_search
from application.orchestrators.searching.strategies.naive_search import NaiveSearchOrchestrator
from domain.enums import EmbedderProviderEnum
from domain.models import (
    EmbeddingConfig,
    FoundChunk,
    NaiveSearchConfig,
)
from infrastructure.naive.embedders.strategies import litellm_embedder


class FakeNaiveRagRepo:
    """In-memory repo for the search flow."""

    def __init__(self, *, embedding_config: EmbeddingConfig | None, found_chunks: list[FoundChunk]):
        self._embedding_config = embedding_config
        self._found_chunks = found_chunks
        self.search_calls: list[dict] = []

    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        return self._embedding_config

    async def search_chunks(
        self, rag_id: int, vector: list[float], limit: int, similarity_threshold: float
    ) -> list[FoundChunk]:
        self.search_calls.append(
            {
                "rag_id": rag_id,
                "vector": vector,
                "limit": limit,
                "similarity_threshold": similarity_threshold,
            }
        )
        return self._found_chunks


class FakeUoW:
    """In-memory unit of work — re-enterable async context manager."""

    def __init__(self, repo: FakeNaiveRagRepo):
        self.naive_rag_repo = repo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _litellm_response(vector: list[float], prompt_tokens: int | None = None):
    usage = None if prompt_tokens is None else type("Usage", (), {"prompt_tokens": prompt_tokens})()
    return type("Resp", (), {"data": [{"embedding": vector}], "usage": usage})()


@pytest.fixture
def embedding_api():
    """litellm's embedding call, the boundary to the provider's HTTP API."""
    mock = AsyncMock(return_value=_litellm_response([0.1, 0.2, 0.3]))
    with patch.object(litellm_embedder.litellm, "aembedding", mock):
        yield mock


_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI,
    api_key="test-key",
    model="text-embedding-3-small",
)


def _make_command(
    *,
    rag_id: int = 1,
    query: str = "find me",
    search_config: NaiveSearchConfig | None = None,
    embedding_api_key: str = "sk-test",
    **request_fields,
) -> RunSearch:
    if search_config is None:
        search_config = NaiveSearchConfig(search_limit=5, similarity_threshold=0.3)
    return RunSearch(
        rag_id=rag_id,
        query=query,
        search_config=search_config,
        embedding_api_key=embedding_api_key,
        **request_fields,
    )


async def test_search_embeds_the_query_and_returns_the_closest_chunks(embedding_api):
    found_chunks = [
        FoundChunk(order=0, similarity=0.91, text="first hit", source="doc-a"),
        FoundChunk(order=1, similarity=0.84, text="second hit", source="doc-b"),
    ]
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=found_chunks)

    response = await NaiveSearchOrchestrator(FakeUoW(repo)).execute(
        _make_command(query="find me", embedding_api_key="sk-request")
    )

    assert response.result == found_chunks
    embedding_request = embedding_api.await_args.kwargs
    assert embedding_request["input"] == ["find me"]
    # The key comes from the request, never from the stored embedding config.
    assert embedding_request["api_key"] == "sk-request"
    assert embedding_request["model"] == "text-embedding-3-small"
    assert repo.search_calls == [
        {
            "rag_id": 1,
            "vector": [0.1, 0.2, 0.3],
            "limit": 5,
            "similarity_threshold": 0.3,
        }
    ]


async def test_embedding_extra_headers_reach_the_embedding_provider(
    embedding_api, monkeypatch
):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])

    await NaiveSearchOrchestrator(FakeUoW(repo)).execute(
        _make_command(embedding_extra_headers={"X-Gateway-Key": "resolved-value"})
    )

    assert embedding_api.await_args.kwargs["extra_headers"] == {"X-Gateway-Key": "resolved-value"}


async def test_request_connection_and_settings_reach_the_embedding_provider(
    embedding_api, monkeypatch
):
    monkeypatch.setattr(litellm_embedder.settings, "CUSTOM_EMBED_BASE_URL", None)
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])

    await NaiveSearchOrchestrator(FakeUoW(repo)).execute(
        _make_command(
            embedding_connection={"api_base": "http://gateway/v1"},
            embedding_parameters={"dimensions": 256},
        )
    )

    assert embedding_api.await_args.kwargs["api_base"] == "http://gateway/v1"
    assert embedding_api.await_args.kwargs["dimensions"] == 256


def test_resolved_headers_and_connection_are_kept_out_of_the_command_repr():
    command = _make_command(
        embedding_extra_headers={"X-Gateway-Key": "resolved-secret"},
        llm_extra_headers={"X-Llm-Key": "resolved-llm-secret"},
        embedding_connection={"api_base": "http://user:resolved-emb-password@gw/v1"},
        llm_connection={"aws_access_key_id": "resolved-llm-key-id"},
    )

    for secret in (
        "resolved-secret",
        "resolved-llm-secret",
        "resolved-emb-password",
        "resolved-llm-key-id",
    ):
        assert secret not in repr(command)


async def test_search_reports_embedding_tokens_and_priced_cost(embedding_api, monkeypatch):
    embedding_api.return_value = _litellm_response([0.1], prompt_tokens=250)
    monkeypatch.setattr(naive_search, "embedding_cost", lambda model, tokens: tokens * 2e-8)
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])

    response = await NaiveSearchOrchestrator(FakeUoW(repo)).execute(_make_command())

    assert response.usage.embedding_tokens == 250
    assert response.usage.embedding_cost_usd == 250 * 2e-8


async def test_search_reports_null_cost_for_unpriced_embedding_model(embedding_api):
    embedding_api.return_value = _litellm_response([0.1], prompt_tokens=9)
    unpriced = _EMBEDDING_CONFIG.model_copy(update={"model": "no-such-embedding-model"})
    repo = FakeNaiveRagRepo(embedding_config=unpriced, found_chunks=[])

    response = await NaiveSearchOrchestrator(FakeUoW(repo)).execute(_make_command())

    assert response.usage.embedding_tokens == 9
    assert response.usage.embedding_cost_usd is None
