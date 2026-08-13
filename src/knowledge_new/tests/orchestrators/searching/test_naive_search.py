from application.orchestrators.searching.strategies import naive_search
from application.orchestrators.searching.strategies.naive_search import NaiveSearchOrchestrator
from domain.enums import EmbedderProviderEnum
from application.results import SearchResult
from domain.models import (
    EmbeddingConfig,
    FoundChunk,
    NaiveSearchConfig,
    SearchRequest,
)


class FakeNaiveRagRepo:
    """In-memory repo for the search flow.

    Records each search_chunks call so tests can assert the embedder's vector and
    the search config were wired through correctly.
    """

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
    """In-memory unit of work — re-enterable async context manager (NaiveSearch enters it twice)."""

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

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return self._vector


_EMBEDDING_CONFIG = EmbeddingConfig(
    provider=EmbedderProviderEnum.OPENAI,
    api_key="test-key",
    model="text-embedding-3-small",
)


async def test_search_success_returns_response_with_found_chunks(monkeypatch):
    found_chunks = [
        FoundChunk(order=0, similarity=0.91, text="first hit", source="doc-a"),
        FoundChunk(order=1, similarity=0.84, text="second hit", source="doc-b"),
    ]
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=found_chunks)
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2, 0.3])
    monkeypatch.setattr(naive_search, "build_embedder", lambda provider, config: embedder)

    request = SearchRequest(
        rag_id=1,
        query="find me",
        search_config=NaiveSearchConfig(search_limit=5, similarity_threshold=0.3),
    )

    response = await NaiveSearchOrchestrator(uow).execute(request)

    assert response == SearchResult(result=found_chunks)
    assert response.result == found_chunks
    assert embedder.embedded == ["find me"]  # the query was embedded
    assert repo.search_calls == [
        {
            "rag_id": 1,
            "vector": [0.1, 0.2, 0.3],  # embedder output flows into the search
            "limit": 5,
            "similarity_threshold": 0.3,
        }
    ]


async def test_search_success_returns_empty_response_when_no_chunks_match(monkeypatch):
    repo = FakeNaiveRagRepo(embedding_config=_EMBEDDING_CONFIG, found_chunks=[])
    uow = FakeUoW(repo)
    embedder = FakeEmbedder(vector=[0.1, 0.2, 0.3])
    monkeypatch.setattr(naive_search, "build_embedder", lambda provider, config: embedder)

    request = SearchRequest(
        rag_id=1,
        query="no matches here",
        search_config=NaiveSearchConfig(search_limit=5, similarity_threshold=0.3),
    )

    response = await NaiveSearchOrchestrator(uow).execute(request)

    assert response == SearchResult(result=[])
    assert response.result == []
    assert embedder.embedded == ["no matches here"]  # flow still ran end-to-end
    assert len(repo.search_calls) == 1  # search was performed, just matched nothing
