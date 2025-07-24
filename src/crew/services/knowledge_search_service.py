import os
import json
import time
from uuid import uuid4
from loguru import logger

from utils.singleton_meta import SingletonMeta
from services.redis_service import RedisService, SyncPubsubSubscriber
from models.request_models import KnowledgeSearchMessage


knowledge_search_get_channel = os.getenv(
    "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
)
knowledge_search_response_channel = os.getenv(
    "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
)


class KnowledgeSearchService(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service

    def search_knowledges(
        self,
        sender: str,
        knowledge_collection_id: int,
        query: str,
        search_limit: int,
        distance_threshold: float,
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
            distance_threshold=distance_threshold,
        )

        self.redis_service.publish(
            channel=knowledge_search_get_channel, message=execution_message.model_dump()
        )

        timeout = 15  # seconds
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:

            if knowledge_callback_receiver.results is not None:
                logger.info(
                    f"Knowledge searching for collection id: {knowledge_callback_receiver.results['collection_id']} completed in {round((time.monotonic() - start_time), 2)} sec. Sender: {sender}"
                )
                self.redis_service.unsubscribe(
                    channels=knowledge_search_response_channel,
                    subscriber=subscriber,
                )
                return knowledge_callback_receiver.results["results"]
            time.sleep(0.1)

        logger.error(f"Search failed: No response received within {timeout} seconds")
        return []


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
        if data.get("uuid") == self.execution_uuid:
            logger.info(f"Search results received: {data}")
            self._results = data

            # TODO: remove logging
            logger.success(f"KnowledgeSearchReceiver, {self._results=}")
            logger.success(
                f"KnowledgeSearchReceiver, collection_id: {self._results['collection_id']}"
            )
            logger.success(
                f"KnowledgeSearchReceiver, results: {self._results['results']}"
            )
