import os
import json
import time
from uuid import uuid4
from loguru import logger
from typing import Optional
from langgraph.types import StreamWriter
from models.graph_models import GraphMessage

from services.graph.events import StopEvent
from utils.singleton_meta import SingletonMeta
from services.redis_service import RedisService, SyncPubsubSubscriber
from models.request_models import (
    KnowledgeSearchMessage,
    KnowledgeQueryResultDTO,
)


knowledge_search_get_channel = os.getenv(
    "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
)
knowledge_search_response_channel = os.getenv(
    "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
)


class KnowledgeSearchService:
    """
    KnowledgeSearchService used by CrewCallbackFactory(for human_input) and by Crew(by Agent for searching)
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
        query: str,
        search_limit: int,
        similarity_threshold: float,
        stop_event: StopEvent | None = None,
    ) -> list[str]:

        execution_uuid = f"{sender}-{str(uuid4())}"

        knowledge_callback_receiver = KnowledgeSearchReceiver(
            execution_uuid=execution_uuid
        )
        subscriber = SyncPubsubSubscriber(knowledge_callback_receiver.callback)
        self.redis_service.subscribe(
            channels=knowledge_search_response_channel,
            subscriber=subscriber,
        )

        execution_message = KnowledgeSearchMessage(
            collection_id=knowledge_collection_id,
            uuid=execution_uuid,
            query=query,
            search_limit=search_limit,
            similarity_threshold=similarity_threshold,
        )

        self.redis_service.publish(
            channel=knowledge_search_get_channel, message=execution_message.model_dump()
        )

        timeout = 15  # seconds
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:

            if knowledge_callback_receiver.results is not None:
                logger.info(
                    f"Knowledge searching for collection id: {knowledge_callback_receiver.results.collection_id} completed in {round((time.monotonic() - start_time), 2)} sec. Sender: {sender}"
                )
                self.redis_service.unsubscribe(
                    channel=knowledge_search_response_channel,
                    subscriber=subscriber,
                )

                if self.writer is not None:
                    self._add_knowledges_to_graph_message(
                        knowledge_results=knowledge_callback_receiver.results,
                    )
                return knowledge_callback_receiver.results.results

            if stop_event is not None:
                stop_event.check_stop()

            time.sleep(0.1)

        logger.error(f"Search failed: No response received within {timeout} seconds")
        return []

    def _add_knowledges_to_graph_message(
        self,
        knowledge_results: KnowledgeQueryResultDTO,
    ):
        chunks_data_list = [chunk.model_dump() for chunk in knowledge_results.chunks]
        knowledge_results_data = {
            "message_type": "extracted_chunks",
            "crew_id": self.crew_id,
            "agent_id": self.agent_id,
            "collection_id": knowledge_results.collection_id,
            "retrieved_chunks": knowledge_results.retrieved_chunks,
            "similarity_threshold": knowledge_results.similarity_threshold,
            "search_limit": knowledge_results.search_limit,
            "knowledge_query": knowledge_results.knowledge_query,
            "chunks": chunks_data_list,
        }
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=self.execution_order,
            message_data=knowledge_results_data,
        )
        self.writer(graph_message)


class KnowledgeSearchReceiver:

    def __init__(self, execution_uuid: str):
        self.execution_uuid = execution_uuid
        self._results = None

    @property
    def results(self):
        return self._results

    def callback(self, message: dict):
        """
        Asynchronous callback to handle search results.
        This function can be used to process the search results as needed.
        """
        data: dict = json.loads(message["data"])
        validated_results = KnowledgeQueryResultDTO.model_validate(data)
        if validated_results.uuid == self.execution_uuid:
            logger.info(f"Search results received: {data}")
            self._results = validated_results

            # TODO: remove logging
            logger.success(f"KnowledgeSearchReceiver, {self._results=}")
            logger.success(
                f"KnowledgeSearchReceiver, collection_id: {self._results.collection_id}"
            )
            logger.success(f"KnowledgeSearchReceiver, results: {self._results.results}")
