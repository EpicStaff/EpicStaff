from typing import Optional

from rag.rag_strategy_factory import RAGStrategyFactory
from rag.base_rag_strategy import BaseRAGStrategy
from settings import UnitOfWork
from utils.singleton_meta import SingletonMeta
from models.redis_models import BaseRagSearchConfig
from services.cancellation_token import CancellationToken


class CollectionProcessorService(metaclass=SingletonMeta):
    """Context class that uses a RAG strategy."""

    def __init__(self):
        self.uow = UnitOfWork()

    def _get_strategy(self, rag_type: str) -> BaseRAGStrategy:
        return RAGStrategyFactory.get_strategy(rag_type)

    def process_rag_indexing(self, rag_id: int, rag_type: str):
        strategy = self._get_strategy(rag_type)
        strategy.process_rag_indexing(rag_id=rag_id)

    def process_preview_chunking(
        self,
        rag_type: str,
        document_config_id: int,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> int:
        """
        Perform preview chunking for a document config.

        Delegates to the appropriate RAG strategy based on rag_type.

        Args:
            rag_type: Type of RAG strategy ("naive", "graph", etc.)
            document_config_id: Generic ID of the document config
            cancellation_token: Optional token to check if job was cancelled

        Returns:
            Number of preview chunks created

        Raises:
            NotImplementedError: If strategy doesn't support preview chunking
            ValueError: If rag_type is not supported
        """
        strategy = self._get_strategy(rag_type)
        return strategy.process_preview_chunking(
            document_config_id=document_config_id,
            cancellation_token=cancellation_token,
        )

    def search(
        self,
        rag_id: int,
        rag_type: str,
        collection_id: int,
        uuid: str,
        query: str,
        rag_search_config: BaseRagSearchConfig,
    ):
        strategy = self._get_strategy(rag_type)
        return strategy.search(
            rag_id=rag_id,
            collection_id=collection_id,
            uuid=uuid,
            query=query,
            rag_search_config=rag_search_config,
        )
