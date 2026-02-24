import asyncio
import contextlib
import os
import json
import redis
import redis.asyncio as async_redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from threading import Lock

from django_app.settings import (
    KNOWLEDGE_DOCUMENT_CHUNK_CHANNEL,
    KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE,
    KNOWLEDGE_INDEXING_CHANNEL,
    STOP_SESSION_CHANNEL,
)
from tables.request_models import (
    ChunkDocumentMessage,
    ChunkDocumentMessageResponse,
    ProcessRagIndexingMessage,
    RealtimeAgentChatData,
    SessionData,
    StopSessionMessage,
)
from utils.singleton_meta import SingletonMeta
from utils.logger import logger


class RedisService(metaclass=SingletonMeta):
    _lock: Lock = Lock()

    def __init__(self):
        self._redis_client = None
        self._pubsub = None
        self._async_redis_client = None
        self._redis_host = os.getenv("REDIS_HOST", "localhost")
        self._redis_port = int(os.getenv("REDIS_PORT", 6379))
        self._redis_password = os.getenv("REDIS_PASSWORD")
        self._retry = Retry(backoff=ExponentialBackoff(cap=3), retries=10)

    def _initialize_redis(self):
        with self._lock:
            if self._redis_client is None:
                self._redis_client = redis.Redis(
                    host=self._redis_host,
                    port=self._redis_port,
                    password=self._redis_password,
                    retry=self._retry,
                )
                self._pubsub = self._redis_client.pubsub()

    def _initialize_async(self):
        if self._async_redis_client is None:
            self._async_redis_client = async_redis.Redis(
                host=self._redis_host,
                port=self._redis_port,
                password=self._redis_password,
                decode_responses=True,
                retry=self._retry,
            )

    @property
    def redis_client(self):
        """Lazy initialize redis_client"""
        if self._redis_client is None:
            self._initialize_redis()
        return self._redis_client

    @property
    def pubsub(self):
        """Lazy initialize pubsub"""
        if self._pubsub is None:
            self._initialize_redis()
        return self._pubsub

    @property
    def async_redis_client(self):
        if self._async_redis_client is None:
            self._initialize_async()
        return self._async_redis_client

    def publish_session_data(self, session_data: SessionData) -> int:
        return self.redis_client.publish(
            "sessions:schema", session_data.model_dump_json()
        )

    def send_user_input(
        self,
        session_id: int,
        node_name: str,
        crew_id: int,
        execution_order: str,
        message: str,
    ) -> None:
        user_input_message = {
            "crew_id": crew_id,
            "node_name": node_name,
            "execution_order": execution_order,
            "text": message,
        }
        channel = f"sessions:{session_id}:user_input"
        self.redis_client.publish(channel, message=json.dumps(user_input_message))
        logger.info(f"Sent user message to: {channel}.")

    def publish_source_collection(self, collection_id) -> None:
        # TODO: move channel name higher.
        channel = "knowledge_sources"
        message = {
            "collection_id": collection_id,
            "event": f"embed collection {collection_id}.",
        }
        self.redis_client.publish(channel=channel, message=json.dumps(message))
        logger.info(f"Sent collection_id: {collection_id} to {channel}.")

    def publish_rag_indexing(
        self, rag_id: int, rag_type: str, collection_id: int
    ) -> None:
        """
        Publish RAG indexing message to knowledge service.

        Args:
            rag_id: ID of the specific RAG implementation (e.g., NaiveRag.naive_rag_id)
            rag_type: Type of RAG ("naive" or "graph")
            collection_id: Source collection ID
        """
        message = ProcessRagIndexingMessage(
            rag_id=rag_id, rag_type=rag_type, collection_id=collection_id
        )
        self.redis_client.publish(
            channel=KNOWLEDGE_INDEXING_CHANNEL, message=message.model_dump_json()
        )
        logger.info(
            f"Sent RAG indexing request to {KNOWLEDGE_INDEXING_CHANNEL}: "
            f"rag_type={rag_type}, rag_id={rag_id}, collection_id={collection_id}"
        )

    def publish_realtime_agent_chat(
        self, rt_agent_chat_data: RealtimeAgentChatData
    ) -> None:
        self.redis_client.publish(
            "realtime_agents:schema", rt_agent_chat_data.model_dump_json()
        )
        logger.info("Sent realtime agent chat to: realtime_agents:schema.")
        logger.debug(f"Schema: {rt_agent_chat_data.model_dump()}.")

    def publish_user_graph_message(
        self, session_id: int, uuid: str, data: dict
    ) -> None:
        channel = os.environ.get("GRAPH_MESSAGE_UPDATE_CHANNEL", "graph:message:update")

        message = {
            "uuid": str(uuid),
            "session_id": session_id,
        }

        self.redis_client.setex(
            name=f"graph:message:{session_id}:{uuid}",
            time=60,
            value=json.dumps(data),
        )

        self.redis_client.publish(channel=channel, message=json.dumps(message))
        logger.info(
            f"Cached for saving graph message data created by user unput: {uuid} in {session_id=}."
        )

    async def redis_get_message(self, channels: list, pubsub):
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.debug(f"message from redis_get_message {message['data']}")
                    yield message
                    await asyncio.sleep(0.01)

        except Exception as e:
            # TODO: fix reconection logic
            logger.warning(f"Redis PubSub connection error: {e}.")
            # if reconnections_left <= 0:
            #     raise

            # # Retry with a new pubsub
            # async for message in self.redis_get_message(
            #     channels, reconnections_left - 1
            # ):
            #     yield message

        finally:
            # Cleanly unsubscribe and close pubsub to avoid Redis leaks
            with contextlib.suppress(Exception):
                # TODO: refactor
                await pubsub.unsubscribe(*channels)
                await pubsub.close()

    async def publish_and_wait_for_chunking(
        self,
        rag_type: str,
        document_config_id: int,
        chunking_job_id: str,
        timeout: float = 50.0,
    ) -> ChunkDocumentMessageResponse:
        """
        Publish chunking request and wait for response.

        Uses async Redis to:
        1. Subscribe to response channel
        2. Publish chunking request
        3. Wait for response with matching chunking_job_id
        4. Return response or raise TimeoutError

        Args:
            rag_type: Type of RAG strategy ("naive", "graph", etc.)
            document_config_id: Generic ID of the document config to chunk
            chunking_job_id: UUID for tracking request/response
            timeout: Max time to wait for response (default: 30s)

        Returns:
            ChunkDocumentMessageResponse from Knowledge service

        Raises:
            asyncio.TimeoutError: If no response within timeout
        """
        response_channel = KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE

        # Create pubsub and subscribe BEFORE publishing
        pubsub = self.async_redis_client.pubsub()
        await pubsub.subscribe(response_channel)

        try:
            # Publish chunking request
            message = ChunkDocumentMessage(
                chunking_job_id=chunking_job_id,
                rag_type=rag_type,
                document_config_id=document_config_id,
            )
            await self.async_redis_client.publish(
                KNOWLEDGE_DOCUMENT_CHUNK_CHANNEL,
                message.model_dump_json(),
            )
            logger.info(
                f"Published chunking request: job_id={chunking_job_id}, "
                f"rag_type={rag_type}, config_id={document_config_id}"
            )

            # Wait for response with matching chunking_job_id
            async with asyncio.timeout(timeout):
                async for msg in pubsub.listen():
                    if msg["type"] == "message":
                        try:
                            data = json.loads(msg["data"])
                            if data.get("chunking_job_id") == chunking_job_id:
                                logger.info(
                                    f"Received chunking response for job_id={chunking_job_id}"
                                )
                                return ChunkDocumentMessageResponse.model_validate(data)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Invalid JSON in chunking response: {msg['data']}"
                            )
                        except Exception as e:
                            logger.warning(f"Error parsing chunking response: {e}")

        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(response_channel)
                await pubsub.close()

    def publish_stop_session(self, session_id) -> int:
        message = StopSessionMessage(session_id=session_id)
        return self.redis_client.publish(
            STOP_SESSION_CHANNEL, json.dumps(message.model_dump())
        )
