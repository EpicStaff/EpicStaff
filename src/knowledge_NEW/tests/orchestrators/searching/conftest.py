from unittest.mock import AsyncMock, Mock

from enums import EmbedderProviderEnum
from models import EmbeddingConfig, FoundChunk


class FakeUoW:
    """In-memory unit of work for searching orchestration tests.

    Each test constructs one with the embedding config and chunk list it
    needs; all repo methods are AsyncMocks so no database is required.
    """

    def __init__(
        self,
        embedding_config: EmbeddingConfig | None,
        chunks: list[FoundChunk],
    ):
        self.naive_rag_repo = Mock()
        self.naive_rag_repo.get_embedding_config = AsyncMock(
            return_value=embedding_config
        )
        self.naive_rag_repo.search_chunks = AsyncMock(return_value=chunks)
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False
