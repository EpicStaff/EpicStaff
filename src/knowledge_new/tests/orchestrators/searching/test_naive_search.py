from application.commands import RunSearch
from application.orchestrators.searching.strategies import naive_search
from application.orchestrators.searching.strategies.naive_search import NaiveSearchOrchestrator
from application.results import SearchResult
from domain.enums import EmbedderProviderEnum
from domain.models import (
    EmbeddingConfig,
    FoundChunk,
    NaiveSearchConfig,
)


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


class FakeEmbedder:
    """Stands in for the external embedding-provider API. Returns a fixed opaque vector."""

    def __init__(self, vector: list[float]):
        self._vector = vector
        self.embedded: list[str] = []
        self.received_api_key: str | None = None

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return self._vector


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


async def test_search_success_returns_response_with_found_chunks(monkeypatch):
    found_chunks = [
        FoundChunk(order=0, similarity=0.91, text="first hit", source="doc-a"),
        FoundChunk(order=1, similarity=0.84, text="second hit", source="doc-b"),
    ]
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=found_chunks)
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2, 0.3])
    monkeypatch.setattr(naive_search, "build_embedder", lambda provider, api_key, config: embedder)

    command = _make_command(query="find me")

    response = await NaiveSearchOrchestrator(uow).execute(command)

    assert response == SearchResult(result=found_chunks)
    assert response.result == found_chunks
    assert embedder.embedded == ["find me"]
    assert repo.search_calls == [
        {
            "rag_id": 1,
            "vector": [0.1, 0.2, 0.3],
            "limit": 5,
            "similarity_threshold": 0.3,
        }
    ]


async def test_search_success_returns_empty_response_when_no_chunks_match(monkeypatch):
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2, 0.3])
    monkeypatch.setattr(naive_search, "build_embedder", lambda provider, api_key, config: embedder)

    command = _make_command(query="no matches here")

    response = await NaiveSearchOrchestrator(uow).execute(command)

    assert response == SearchResult(result=[])
    assert response.result == []
    assert embedder.embedded == ["no matches here"]
    assert len(repo.search_calls) == 1


async def test_embedding_api_key_forwarded_to_build_embedder(monkeypatch):
    received: list[tuple] = []

    def capturing_build_embedder(provider, api_key, config):
        received.append((provider, api_key, config))
        return FakeEmbedder(vector=[0.9])

    monkeypatch.setattr(naive_search, "build_embedder", capturing_build_embedder)

    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])
    uow = FakeUoW(repo)
    command = _make_command(embedding_api_key="sk-forwarded")

    await NaiveSearchOrchestrator(uow).execute(command)

    assert len(received) == 1
    provider, api_key, config = received[0]
    assert api_key == "sk-forwarded"
    assert provider == EmbedderProviderEnum.OPENAI
    assert config is _EMBEDDING_CONFIG


async def test_empty_embedding_api_key_is_forwarded(monkeypatch):
    received_keys: list[str] = []

    def capturing_build_embedder(provider, api_key, config):
        received_keys.append(api_key)
        return FakeEmbedder(vector=[0.1])

    monkeypatch.setattr(naive_search, "build_embedder", capturing_build_embedder)

    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])
    uow = FakeUoW(repo)
    command = _make_command(embedding_api_key="")

    await NaiveSearchOrchestrator(uow).execute(command)

    assert received_keys == [""]
