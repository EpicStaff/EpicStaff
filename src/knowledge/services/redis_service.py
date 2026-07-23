import threading

import redis
import redis.asyncio as aioredis
from redis.client import PubSub
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
import json
from loguru import logger
from utils.singleton_meta import SingletonMeta


class RedisService(metaclass=SingletonMeta):
    _sync_client_lock = threading.Lock()

    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password

        self.aioredis_client: aioredis.Redis | None = None
        self._sync_redis_client: redis.Redis | None = None
        self._retry = Retry(backoff=ExponentialBackoff(cap=3), retries=10)

    async def connect(self):
        self.aioredis_client = await aioredis.from_url(
            f"redis://{self.host}:{self.port}",
            password=self.password,
            decode_responses=True,
            retry=self._retry,
        )

    async def async_subscribe(self, channel: str) -> PubSub:
        pubsub = self.aioredis_client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def async_publish(self, channel: str, message: object):
        await self.aioredis_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")

    @property
    def sync_client(self) -> redis.Redis:
        """
        Lazily initialized synchronous Redis client.

        Used for publishing from code that runs inside a ThreadPoolExecutor
        (e.g. NaiveRAGStrategy.process_rag_indexing), where there is no
        running asyncio event loop to `await async_publish(...)` on.
        """
        if self._sync_redis_client is None:
            with self._sync_client_lock:
                if self._sync_redis_client is None:
                    self._sync_redis_client = redis.Redis(
                        host=self.host,
                        port=self.port,
                        password=self.password,
                        decode_responses=True,
                        retry=self._retry,
                    )
        return self._sync_redis_client

    def publish(self, channel: str, message: object) -> None:
        """Synchronous publish counterpart to `async_publish`."""
        self.sync_client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}' (sync).")
