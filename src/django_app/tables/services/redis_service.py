import contextlib
import os
import json
import redis
import redis.asyncio as async_redis
from threading import Lock

from tables.request_models import RealtimeAgentChatData, SessionData
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

    def _initialize_redis(self):
        with self._lock:
            if self._redis_client is None:
                self._redis_client = redis.Redis(
                    host=self._redis_host, port=self._redis_port
                )
                self._pubsub = self._redis_client.pubsub()

    def _initialize_async(self):
        if self._async_redis_client is None:
            self._async_redis_client = async_redis.Redis(
                host=self._redis_host, port=self._redis_port, decode_responses=True
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

    def publish_session_data(self, session_data: SessionData) -> None:
        self.redis_client.publish(f"sessions:schema", session_data.model_dump_json())

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
            "event": f"created new collection {collection_id}.",
        }
        self.redis_client.publish(channel=channel, message=json.dumps(message))
        logger.info(f"Sent collection_id: {collection_id} to {channel}.")

    def publish_add_source(self, collection_id) -> None:
        channel = "knowledge_sources"
        message = {
            "collection_id": collection_id,
            "event": f"add source to collection {collection_id}.",
        }
        self.redis_client.publish(channel=channel, message=json.dumps(message))
        logger.info(f"Sent collection_id: {collection_id} to {channel}.")

    def publish_realtime_agent_chat(
        self, rt_agent_chat_data: RealtimeAgentChatData
    ) -> None:
        self.redis_client.publish(
            f"realtime_agents:schema", rt_agent_chat_data.model_dump_json()
        )
        logger.info(f"Sent realtime agent chat to: realtime_agents:schema.")
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

    async def redis_get_message(self, channels: list, reconnections_left=2):
        try:
            pubsub = self.async_redis_client.pubsub()
            await pubsub.subscribe(*channels)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield message

        except Exception as e:
            logger.warning(
                f"Redis PubSub connection error: {e}. Reinitializing pubsub. Tries left #{reconnections_left}"
            )
            if reconnections_left <= 0:
                raise

            # Retry with a new pubsub
            async for message in self.redis_get_message(channels, reconnections_left - 1):
                yield message

        finally:
            # Cleanly unsubscribe and close pubsub to avoid Redis leaks
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(*channels)
                await pubsub.close()

