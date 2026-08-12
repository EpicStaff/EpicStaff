import abc

from domain.enums import (
    DocumentStatusEnum,
    FileExtensionEnum,
)
from domain.models import (
    Document,
    EmbeddingConfig,
    FoundChunk,
    IndexedChunk,
    PreviewChunk,
    Rag,
)
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_input import TextDocument


class AbstractNaiveRagRepository(abc.ABC):
    """Abstract repository for naive RAG persistence operations."""

    @abc.abstractmethod
    async def get_rag(self, rag_id: int) -> Rag | None:
        """Return the `Rag` aggregate identified by `rag_id`, or `None` if not found.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def update_rag(self, rag: Rag):
        """Persist `rag`'s current status and `indexing_document_ids`.

        Args:
            rag: The `Rag` aggregate.
        """

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
    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[Document]:
        """Return all `Document` objects belonging to `rag_id`.

        Args:
            rag_id: Primary key of the RAG collection.
            ids: Primary keys of the document configs.
        """

    @abc.abstractmethod
    async def has_completed_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with COMPLETED status.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def has_failed_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with FAILED status.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def has_outdated_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with OUTDATED status.

        Args:
            rag_id: Primary key of the RAG collection.
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

    @abc.abstractmethod
    async def get_document_content(
        self, rag_id: int, document_id: int
    ) -> tuple[bytes, FileExtensionEnum]:
        """Return the raw file bytes and file extension of `document_id` within RAG collection `rag_id`.

        Args:
            rag_id: Primary key of the RAG collection.
            document_id: Primary key of the document (config) whose file content to load.
        """


class AbstractGraphRagRepository(abc.ABC):
    @abc.abstractmethod
    async def get_rag(self, rag_id: int) -> Rag | None:
        """Return the `Rag` aggregate identified by `rag_id`, or `None` if not found.

        Args:
            rag_id: Primary key of the RAG collection.
        """

    @abc.abstractmethod
    async def update_rag(self, rag: Rag):
        """Persist `rag`'s current status and `indexing_document_ids`.

        Args:
            rag: The `Rag` aggregate.
        """

    @abc.abstractmethod
    async def get_documents(self, rag_id: int, ids: frozenset[int]) -> list[TextDocument]:
        """Return `TextDocument` objects for the given `ids` within `rag_id`, with text extracted from raw content.

        Args:
            rag_id: Primary key of the GraphRAG collection.
            ids: Primary keys of the documents to retrieve.
        """

    @abc.abstractmethod
    async def get_indexed_documents_excluding(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        pass

    @abc.abstractmethod
    async def get_config(self, rag_id: int) -> GraphRagConfig:
        """Return a fully-populated `GraphRagConfig` assembled from the DB records for `rag_id`.

        Args:
            rag_id: Primary key of the GraphRAG collection.
        """

    @abc.abstractmethod
    async def update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: DocumentStatusEnum,
    ):
        """Persist status of `documents` within the RAG collection `rag_id`.

        Args:
            rag_id: Primary key of the GraphRAG collection.
            ids: Primary keys of the documents to retrieve.
            status: Status of document.
        """

    @abc.abstractmethod
    async def has_completed_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with COMPLETED status.

        Args:
            rag_id: Primary key of the GraphRAG collection.
        """

    @abc.abstractmethod
    async def has_failed_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with FAILED status.

        Args:
            rag_id: Primary key of the GraphRAG collection.
        """

    @abc.abstractmethod
    async def has_outdated_document(self, rag_id: int) -> bool:
        """Return True if `rag_id` has at least one document with OUTDATED status.

        Args:
            rag_id: Primary key of the GraphRAG collection.
        """
