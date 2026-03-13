import os
import json
import time
from uuid import uuid4
from typing import Dict, Any, Optional
from loguru import logger
from langgraph.types import StreamWriter

from src.crew.models.graph_models import GraphMessage
from src.crew.services.graph.events import StopEvent
from src.crew.services.redis_service import RedisService, SyncPubsubSubscriber
from src.shared.models import (
    RagSearchConfig,
    NaiveRagSearchConfig,
    GraphRagSearchConfig,
    BaseKnowledgeSearchMessage,
    BaseKnowledgeSearchMessageResponse,
)


knowledge_search_get_channel = os.getenv(
    "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
)
knowledge_search_response_channel = os.getenv(
    "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
)


class RagSearchConfigFactory:
    """
    Factory class to build RAG search configs from dict based on rag_type.
    """

    _config_builders = {
        "naive": lambda config: NaiveRagSearchConfig(**config),
        "graph": lambda config: GraphRagSearchConfig(**config),
        # Future RAG types
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
        builder = cls._config_builders.get(rag_type)
        if not builder:
            raise ValueError(
                f"Unsupported RAG type: {rag_type}. "
                f"Supported types: {list(cls._config_builders.keys())}"
            )

        return builder(config_dict)


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
        timeout: int = 15,
    ) -> list[str]:
        """
        Search knowledge using specified RAG implementation.

        Args:
            sender: Identifier of the sender
            rag_type_id: RAG type and ID in format "rag_type:id" (e.g., "naive:6")
            query: Search query text
            rag_search_config: RAG-specific search parameters dict
            stop_event: Optional event to stop execution
            timeout: Timeout in seconds for waiting response

        Returns:
            List of knowledge results (strings)
        """

        rag_type, rag_id = self._parse_rag_type_id(rag_type_id)

        search_config = RagSearchConfigFactory.build(rag_type, rag_search_config)

        execution_uuid = f"{sender}-{str(uuid4())}"

        # Setup response receiver
        knowledge_callback_receiver = KnowledgeSearchReceiver(
            execution_uuid=execution_uuid
        )
        subscriber = SyncPubsubSubscriber(knowledge_callback_receiver.callback)
        self.redis_service.subscribe(
            channels=knowledge_search_response_channel,
            subscriber=subscriber,
        )

        # Create and send message
        execution_message = BaseKnowledgeSearchMessage(
            collection_id=knowledge_collection_id,
            rag_id=rag_id,
            rag_type=rag_type,
            uuid=execution_uuid,
            query=query,
            rag_search_config=search_config,
        )

        self.redis_service.publish(
            channel=knowledge_search_get_channel,
            message=execution_message.model_dump(),
        )

        # Wait for response
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if knowledge_callback_receiver.results is not None:
                elapsed = round((time.monotonic() - start_time), 2)
                logger.info(
                    f"Knowledge search completed for {rag_type_id} in {elapsed}s. "
                    f"Sender: {sender}"
                )
                self.redis_service.unsubscribe(
                    channel=knowledge_search_response_channel,
                    subscriber=subscriber,
                )

                if self.writer is not None:
                    self._add_knowledges_to_graph_message(
                        knowledge_results=knowledge_callback_receiver.results,
                        token_usage=knowledge_callback_receiver.token_usage,
                    )
                return knowledge_callback_receiver.results.results

            if stop_event is not None:
                stop_event.check_stop()

            time.sleep(0.1)

        # Cleanup
        self.redis_service.unsubscribe(
            channel=knowledge_search_response_channel,
            subscriber=subscriber,
        )
        logger.error(f"Search failed: No response received within {timeout}s")
        raise TimeoutError(
            f"Knowledge search timeout for {rag_type_id} after {timeout}s"
        )

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
        self, knowledge_results: BaseKnowledgeSearchMessageResponse, token_usage: dict
    ):
        chunks_data_list = [chunk.model_dump() for chunk in knowledge_results.chunks]
        knowledge_results_data = {
            "message_type": "extracted_chunks",
            "crew_id": self.crew_id,
            "agent_id": self.agent_id,
            "collection_id": knowledge_results.collection_id,
            "retrieved_chunks": knowledge_results.retrieved_chunks,
            "knowledge_query": knowledge_results.query,
            "rag_search_config": knowledge_results.rag_search_config.model_dump(),
            "chunks": chunks_data_list,
            "token_usage": token_usage,
        }
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=self.execution_order,
            message_data=knowledge_results_data,
        )
        self.writer(graph_message)


class KnowledgeSearchReceiver:
    """
    Callback receiver for knowledge search results from Redis.
    """

    def __init__(self, execution_uuid: str):
        self.execution_uuid = execution_uuid
        self._token_usage = {}
        self._results = None

    @property
    def results(self):
        return self._results

    @property
    def token_usage(self):
        return self._token_usage

    def callback(self, message: dict):
        """
        Callback to handle search results from Redis pub/sub.

        Args:
            message: Redis message dict containing search results
        """
        try:
            data: dict = json.loads(message["data"])
            validated_results = BaseKnowledgeSearchMessageResponse.model_validate(data)
            if validated_results.uuid == self.execution_uuid:
                logger.info(f"Search results received for UUID: {self.execution_uuid}")
                self._results = validated_results
                logger.debug(f"Results: {self._results.results}")
                self._token_usage = data.get("token_usage", {})
                logger.info(f"Tokens used for knowledge retrieval: {self._token_usage}")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing search results: {e}")
