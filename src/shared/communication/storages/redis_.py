from datetime import timedelta

from redis import Redis as SyncRedis, RedisError
from redis.asyncio import Redis as AsyncRedis

from communication.error_handler import handle_error
from communication.errors import StorageOperationError
from communication.storages.abstract import AbstractStorage


class RedisStorage(AbstractStorage):
    """Redis implementation of storage.

    Args:
        url: Redis connection URL (e.g. redis://host:6379/0).
        ttl: Lifetime of each entry, in seconds or as a timedelta. Defaults to 1h.
    """

    def __init__(self, url: str, ttl: int | timedelta = timedelta(hours=1)):
        self._sync_client = SyncRedis.from_url(url)
        self._async_client = AsyncRedis.from_url(url)
        self._ttl = ttl

    def put(self, key: str, payload: bytes):
        with handle_error(RedisError, StorageOperationError, "put", key):
            self._sync_client.set(key, payload, self._ttl)

    async def aput(self, key: str, payload: bytes):
        with handle_error(RedisError, StorageOperationError, "aput", key):
            await self._async_client.set(key, payload, self._ttl)

    def get(self, key: str) -> bytes | None:
        with handle_error(RedisError, StorageOperationError, "get", key):
            return self._sync_client.get(key)

    async def aget(self, key: str) -> bytes | None:
        with handle_error(RedisError, StorageOperationError, "aget", key):
            return await self._async_client.get(key)

    def remove(self, key: str):
        with handle_error(RedisError, StorageOperationError, "remove", key):
            self._sync_client.delete(key)

    async def aremove(self, key: str):
        with handle_error(RedisError, StorageOperationError, "aremove", key):
            await self._async_client.delete(key)
