import abc
import functools
import inspect
from typing import Callable, Any, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from errors import RepositoryError
from models import EmbeddingConfig, Document, PreviewChunk, IndexedChunk, FoundChunk


class RepositoryErrorWrapper:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name, obj in vars(cls).items():
            if inspect.iscoroutinefunction(obj) and not name.startswith("_"):
                setattr(
                    cls,
                    name,
                    cls.__wrap_error_to_repository_error(obj),
                )

    @staticmethod
    def __wrap_error_to_repository_error(func: Callable[..., Awaitable]):
        @functools.wraps(func)
        async def wrap(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except RepositoryError:
                raise
            except Exception as e:
                raise RepositoryError(function=func) from e

        return wrap


class BaseSQLAlchemyRepository:
    """SQLAlchemy session holder for concrete repository implementations."""

    def __init__(self, session: AsyncSession):
        self._session = session


class AbstractNaiveRagRepository(RepositoryErrorWrapper, abc.ABC):
    """Abstract repository for naive RAG persistence operations."""

    @abc.abstractmethod
    async def get_embedding_config(self, rag_id: int) -> EmbeddingConfig | None:
        """Return the `EmbeddingConfig` for `rag_id`, or `None` if not found.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def get_document(self, rag_id: int, document_id: int) -> Document | None:
        """Return `Document` identified by `document_id` within `rag_id`, or `None` if not found.

        Args:
            rag_id: Primary key of the RAG collection.
            document_id: Primary key of the document.
        """

    @abc.abstractmethod
    async def get_all_documents(self, rag_id: int) -> list[Document]:
        """Return all `Document` objects belonging to `rag_id`.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def update_rag_status(self, rag_id: int, status: str):
        """Persist a new status string for the RAG collection identified by `rag_id`.

        Args:
            rag_id: Primary key of the RAG collection.
            status: New status value to persist.
        """

    @abc.abstractmethod
    async def save_preview_chunks(self, document_id: int, chunks: list[PreviewChunk]):
        """Persist `chunks` as preview chunks for `document_id`, replacing any existing preview.

        Args:
            document_id: Primary key of the document.
            chunks: Preview chunks to persist.
        """

    @abc.abstractmethod
    async def save_indexed_chunks(self, document_id: int, chunks: list[IndexedChunk]):
        """Persist `chunks` as indexed (vector-searchable) chunks for `document_id`.

        Args:
            document_id: Primary key of the document.
            chunks: Indexed chunks to persist.
        """

    @abc.abstractmethod
    async def update_document(self, rag_id: int, document: Document):
        """Persist mutations on `document` within the RAG collection `rag_id`.

        Args:
            rag_id: Primary key of the RAG collection.
            document: Document instance carrying the updated state.
        """

    @abc.abstractmethod
    async def search_chunks(
        self,
        rag_id: int,
        vector: list[float],
        limit: int,
        similarity_threshold: float,
    ) -> list[FoundChunk]:
        """Return the top-`limit` chunks whose embedding is within `similarity_threshold` of `vector`.

        Args:
            rag_id: Primary key of the RAG collection to search within.
            vector: Query embedding to compare against stored chunk embeddings.
            limit: Maximum number of chunks to return.
            similarity_threshold: Maximum distance threshold for a chunk to be included.
        """
