import asyncio
import json
import socket
from collections.abc import AsyncIterable
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from utils.singleton_meta import SingletonMeta


class RedisService(metaclass=SingletonMeta):
    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password

        self.client: Redis | None = None
        self._retry = Retry(backoff=ExponentialBackoff(cap=3), retries=10)

    async def connect(self):
        self.client = Redis.from_url(
            f"redis://{self.host}:{self.port}",
            password=self.password,
            decode_responses=True,
            retry=self._retry,
            socket_keepalive=True,
            socket_keepalive_options={
                socket.TCP_KEEPIDLE: 30,
                socket.TCP_KEEPINTVL: 10,
                socket.TCP_KEEPCNT: 3,
            },
            socket_connect_timeout=5,
        )

    async def async_publish(self, channel: str, message: object):
        await self.client.publish(channel, json.dumps(message))
        logger.info(f"Message published to channel '{channel}'.")

    async def listen(self, channel: str) -> AsyncIterable[dict[str, Any]]:
        if self.client is None:
            raise RuntimeError("connect() not called")

        backoff = 5
        while True:
            async with self.client.pubsub() as pubsub:
                try:
                    await pubsub.subscribe(channel)
                    backoff = 5
                    async for msg in pubsub.listen():
                        yield msg
                except (RedisConnectionError, RedisTimeoutError) as e:
                    logger.error("{} listen dropped. Resubscribe in {}s. Error: {}", channel, backoff, e)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff + 5, 30)