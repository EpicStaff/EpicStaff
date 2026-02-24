from abc import ABC, abstractmethod
from typing import Optional
from services.cancellation_token import CancellationToken


class BaseRAGStrategy(ABC):
    """
    Base interface for all RAG strategies.

    All RAG-specific strategies (NaiveRAGStrategy, GraphRAGStrategy, etc.)
    inherit from this base class and implement RAG-specific operations.

    Key Change: All methods now work with rag_id (NOT collection_id).
    """

    @abstractmethod
    def process_rag_indexing(self, rag_id: int, collection_id: int):
        """
        Perform indexing / embedding for a RAG implementation.

        Args:
            rag_id: ID of the specific RAG implementation (naive_rag_id, graph_rag_id, etc.)
            collection_id: ID of the source collection (for getting documents)

        Note: rag_id is RAG-specific (naive_rag_id for NaiveRag, graph_rag_id for GraphRag).
        """
        pass

    @abstractmethod
    def search(self, rag_id: int, uuid: str, query: str, **kwargs):
        """
        Perform search for a RAG implementation.

        Args:
            rag_id: ID of the specific RAG implementation (naive_rag_id, graph_rag_id, etc.)
            uuid: Request UUID
            query: Search query
            **kwargs: Additional search parameters (search_limit, similarity_threshold, etc.)

        Returns:
            Dict with search results

        Note: rag_id is RAG-specific (naive_rag_id for NaiveRag, graph_rag_id for GraphRag).
        """
        pass

    def process_preview_chunking(
        self,
        document_config_id: int,
        cancellation_token: Optional["CancellationToken"] = None,
    ) -> int:
        """
        Perform preview chunking for a document config.

        This is an optional method - not all RAG strategies support chunking.
        Override in subclass to implement strategy-specific preview chunking.

        Note: Cleanup of old preview chunks is handled internally by the
        implementation (before new chunking or during indexing).

        Args:
            document_config_id: Generic ID of the document config
                (e.g., naive_rag_document_config_id for NaiveRAG)
            cancellation_token: Optional token to check if job was cancelled.

        Returns:
            Number of preview chunks created

        Raises:
            NotImplementedError: If strategy doesn't support preview chunking
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support preview chunking."
        )

    # Optional shared behavior
    def get_embedder(self, rag_id: int):
        """
        Return an embedder if strategy uses one.

        Args:
            rag_id: ID of the specific RAG implementation

        Raises:
            NotImplementedError: If strategy doesn't use embeddings
        """
        raise NotImplementedError("This strategy does not use embeddings.")

    def get_llm(self):
        """
        Return LLM model if needed (GraphRAG, AgentRAG, etc.).

        Raises:
            NotImplementedError: If strategy doesn't use an LLM
        """
        raise NotImplementedError("This strategy does not use an LLM.")
