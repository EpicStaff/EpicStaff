from unittest.mock import AsyncMock, patch

import pytest
from application.commands import RunSearch
from application.orchestrators.searching.strategies.naive_search import NaiveSearchOrchestrator
from application.results import SearchResult
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


def _litellm_response(vector: list[float]):
    return type("Resp", (), {"data": [{"embedding": vector}]})()


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
    llm_api_key: str | None = None,
) -> RunSearch:
    if search_config is None:
        search_config = NaiveSearchConfig(search_limit=5, similarity_threshold=0.3)
    return RunSearch(
        rag_id=rag_id,
        query=query,
        search_config=search_config,
        embedding_api_key=embedding_api_key,
        llm_api_key=llm_api_key,
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

    assert response == SearchResult(result=found_chunks)
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
