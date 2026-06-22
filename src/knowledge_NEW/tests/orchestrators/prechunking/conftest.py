from unittest.mock import AsyncMock, Mock

from enums import ChunkStrategyEnum, DocumentStatusEnum
from models import ChunkingConfig, Document


class FakeUoW:
    """In-memory unit of work for orchestration tests.

    Each test constructs one with the document it needs; repo calls are
    replaced with AsyncMocks so no database is required.
    """

    def __init__(self, document: Document | None):
        self.naive_rag_repo = Mock()
        self.naive_rag_repo.get_document = AsyncMock(return_value=document)
        self.naive_rag_repo.update_document = AsyncMock()
        self.naive_rag_repo.save_preview_chunks = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def make_document() -> Document:
    """Return a minimal Document in NEW status with a CHARACTER chunk config."""
    return Document(
        id=7,
        name="doc.txt",
        content=b"hello",
        status=DocumentStatusEnum.NEW,
        config=ChunkingConfig(
            chunk_strategy=ChunkStrategyEnum.CHARACTER,
            chunk_size=10,
            chunk_overlap=0,
        ),
    )
