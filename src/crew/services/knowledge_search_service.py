import os
import threading
from typing import Dict, Any, Optional
from loguru import logger
from langgraph.types import StreamWriter

from models.graph_models import GraphMessage
from services.graph.events import StopEvent
from services.redis_service import RedisService
from constants.constants import (
    NAIVE_RAG_SEARCH_TIMEOUT,
    GRAPH_RAG_SEARCH_TIMEOUT,
    DEFAULT_RAG_SEARCH_TIMEOUT,
)
from src.shared.communication import Message
from services.communication import producer, consumer
from services.communication_schemas import (
    NaiveSearchConfig,
    GraphSearchConfig,
    RagSearchConfig,
    SearchRequest,
    SearchResponse,
    CancelRequest,
)


knowledge_search_get_channel = os.getenv(
    "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
)
knowledge_search_response_channel = os.getenv(
    "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
)
knowledge_cancel_channel = os.getenv("KNOWLEDGE_CANCEL_CHANNEL", "knowledge:cancel")


class RagSearchConfigFactory:
    """
    Factory class to build RAG search configs from dict based on rag_type.
    """

    _configs = {
        "naive": NaiveSearchConfig,
        "graph": GraphSearchConfig,
    }

    _timeouts = {
        "naive": NAIVE_RAG_SEARCH_TIMEOUT,
        "graph": GRAPH_RAG_SEARCH_TIMEOUT,
    }

    @classmethod
    def build(cls, rag_type: str, config_dict: Dict[str, Any]) -> RagSearchConfig:
        """
        Build appropriate RagSearchConfig based on rag_type.

        Args:
            rag_type: Type of RAG ("naive", "graph", etc.)
            config_dict: Dict with RAG-specific parameters

        Returns:
            Appropriate RagSearchConfig subclass instance
        """
        config_class = cls._configs.get(rag_type)
        if not config_class:
            raise ValueError(
                f"Unsupported RAG type: {rag_type}. "
                f"Supported types: {list(cls._configs.keys())}"
            )

        return config_class(**config_dict)

    @classmethod
    def get_timeout(cls, rag_type: str) -> int:
        """
        Get timeout for a given RAG type.
        """
        return cls._timeouts.get(rag_type, DEFAULT_RAG_SEARCH_TIMEOUT)


class KnowledgeSearchService:
    """
    Service for searching knowledge using different RAG implementations.
    """

    def __init__(
        self,
        redis_service: RedisService,
        session_id: int | None = None,
        node_name: str | None = None,
        execution_order: int | None = None,
        crew_id: int | None = None,
        agent_id: int | None = None,
        stream_writer: Optional["StreamWriter"] = None,
    ):
        self.redis_service = redis_service
        self.session_id = session_id
        self.node_name = node_name
        self.crew_id = crew_id
        self.agent_id = agent_id
        self.execution_order = execution_order
        self.writer = stream_writer

    def search_knowledges(
        self,
        sender: str,
        knowledge_collection_id: int,
        rag_type_id: str,
        query: str,
        rag_search_config: Dict[str, Any],
        stop_event: Optional[StopEvent] = None,
        timeout: Optional[int] = None,
    ) -> list[str]:
        """
        Search knowledge using specified RAG implementation.

        Args:
            sender: Identifier of the sender
            rag_type_id: RAG type and ID in format "rag_type:id" (e.g., "naive:6")
            query: Search query text
            rag_search_config: RAG-specific search parameters dict
            stop_event: Optional event to stop execution
            timeout: Timeout in seconds. If None, resolved automatically by rag_type.

        Returns:
            List of knowledge results (strings)
        """

        rag_type, rag_id = self._parse_rag_type_id(rag_type_id)

        if timeout is None:
            timeout = RagSearchConfigFactory.get_timeout(rag_type)

        search_config = RagSearchConfigFactory.build(rag_type, rag_search_config)

        request = SearchRequest(rag_id=rag_id, query=query, search_config=search_config)

        producer.send(
            knowledge_search_get_channel,
            Message(payload=request.model_dump()),
        )
        logger.info(
            "Sent knowledge search rag_id=%s sender=%s query=%r", rag_id, sender, query
        )

        search_done = threading.Event()
        if stop_event is not None:
            self._cancel_search_on_stop(request, stop_event, search_done)
        try:
            msg = consumer.receive(knowledge_search_response_channel, timeout=timeout)
        finally:
            search_done.set()
        if msg is None:
            raise TimeoutError(
                f"Knowledge search timeout for {rag_type_id} after {timeout}s"
            )

        response = SearchResponse(**msg.payload)
        if self.writer is not None:
            self._add_knowledges_to_graph_message(response, knowledge_collection_id)

        return [chunk.text for chunk in response.chunks]

    @staticmethod
    def _cancel_search_on_stop(
        request: SearchRequest,
        stop_event: StopEvent,
        search_done: threading.Event,
    ) -> None:
        def _watch() -> None:
            while not search_done.wait(0.1):
                if stop_event.is_set():
                    producer.send(
                        knowledge_cancel_channel,
                        Message(
                            payload=CancelRequest(
                                target_request=request.model_dump()
                            ).model_dump()
                        ),
                    )
                    logger.info(
                        "Sent knowledge search cancellation rag_id=%s", request.rag_id
                    )
                    return

        threading.Thread(target=_watch, daemon=True).start()

    @staticmethod
    def _parse_rag_type_id(rag_type_id: str) -> tuple[str, int]:
        """
        Parse rag_type_id string into type and ID.

        Args:
            rag_type_id: String in format "rag_type:id" (e.g., "naive:6")

        Returns:
            Tuple of (rag_type, rag_id)
        """
        try:
            rag_type, rag_id_str = rag_type_id.split(":", 1)
            rag_id = int(rag_id_str)
            return rag_type, rag_id
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Invalid rag_type_id format: '{rag_type_id}'. "
                f"Expected format: 'rag_type:id' (e.g., 'naive:6')"
            ) from e

    def _add_knowledges_to_graph_message(
        self, response: SearchResponse, collection_id: int
    ):
        knowledge_results_data = {
            "message_type": "extracted_chunks",
            "crew_id": self.crew_id,
            "agent_id": self.agent_id,
            "collection_id": collection_id,
            "retrieved_chunks": len(response.chunks),
            "knowledge_query": response.request.query,
            "rag_search_config": response.request.search_config.model_dump(),
            "chunks": [chunk.model_dump() for chunk in response.chunks],
            "token_usage": {},  # not yet in new contract thats why empty
        }
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=self.execution_order,
            message_data=knowledge_results_data,
        )
        self.writer(graph_message)
