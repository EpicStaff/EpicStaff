from unittest.mock import AsyncMock, Mock

from enums import ChunkStrategyEnum, DocumentStatusEnum, EmbedderProviderEnum
from models import ChunkingConfig, Document, EmbeddingConfig, PreviewChunk


class FakeUoW:
    """In-memory unit of work for indexing orchestration tests.

    Each test constructs one with the embedding config and document list it
    needs; all repo methods are AsyncMocks so no database is required.
    """

    def __init__(
        self,
        embedding_config: EmbeddingConfig | None,
        documents: list[Document],
    ):
        self.naive_rag_repo = Mock()
        self.naive_rag_repo.get_embedding_config = AsyncMock(
            return_value=embedding_config
        )
        self.naive_rag_repo.get_all_documents = AsyncMock(return_value=documents)
        self.naive_rag_repo.update_document = AsyncMock()
        self.naive_rag_repo.save_indexed_chunks = AsyncMock()
        self.naive_rag_repo.update_rag_status = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_document(doc_id: int = 1, *, with_preview: bool = False) -> Document:
    """Return a minimal Document in NEW status with a CHARACTER chunk config.

    Args:
        doc_id: The document's identity value.
        with_preview: When True, pre-populate one preview chunk so the indexer
            skips extraction/chunking and reuses the existing chunks.
    """
    return Document(
        id=doc_id,
        name="d.txt",
        content=b"x",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=10,
            chunk_overlap=0,
        ),
        preview_chunks=[PreviewChunk(text="a")] if with_preview else [],
    )
