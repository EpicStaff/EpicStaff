from datetime import timedelta

import fakeredis
import fakeredis.aioredis
import pytest
import redis

from communication.errors import StorageOperationError
from communication.storages.redis_ import RedisStorage


def _make_storage(ttl: int | timedelta = timedelta(hours=1)) -> RedisStorage:
    storage = RedisStorage.__new__(RedisStorage)
    storage._ttl = ttl
    storage._sync_client = fakeredis.FakeStrictRedis()
    storage._async_client = fakeredis.aioredis.FakeRedis()
    return storage


class TestPutGetRoundtrip:
    def test_put_then_get_returns_same_bytes(self):
        storage = _make_storage()
        storage.put("key1", b"hello world")
        result = storage.get("key1")
        assert result == b"hello world"

    def test_get_missing_key_returns_none(self):
        storage = _make_storage()
        result = storage.get("nonexistent")
        assert result is None

    def test_remove_deletes_key(self):
        storage = _make_storage()
        storage.put("key2", b"data")
        storage.remove("key2")
        assert storage.get("key2") is None

    def test_ttl_applied_on_put(self):
        """put uses the configured TTL — verify key is stored under a TTL."""
        storage = _make_storage(ttl=60)
        storage.put("key3", b"ttl-data")
        # fakeredis supports TTL introspection
        ttl = storage._sync_client.ttl("key3")
        assert ttl > 0


class TestSyncErrorWrapping:
    def test_get_redis_error_raises_storage_operation_error(self, monkeypatch):
        storage = _make_storage()

        def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated get error")

        monkeypatch.setattr(storage._sync_client, "get", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            storage.get("any-key")

        error = exc_info.value
        assert error.operation == "get"
        assert error.key == "any-key"
        assert isinstance(error.__cause__, redis.RedisError)

    def test_put_redis_error_raises_storage_operation_error(self, monkeypatch):
        storage = _make_storage()

        def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated put error")

        monkeypatch.setattr(storage._sync_client, "set", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            storage.put("put-key", b"payload")

        error = exc_info.value
        assert error.operation == "put"
        assert error.key == "put-key"
        assert isinstance(error.__cause__, redis.RedisError)

    def test_remove_redis_error_raises_storage_operation_error(self, monkeypatch):
        storage = _make_storage()

        def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated delete error")

        monkeypatch.setattr(storage._sync_client, "delete", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            storage.remove("del-key")

        error = exc_info.value
        assert error.operation == "remove"
        assert error.key == "del-key"
        assert isinstance(error.__cause__, redis.RedisError)


class TestAsyncPutGetRoundtrip:
    @pytest.mark.asyncio
    async def test_aput_then_aget_returns_same_bytes(self):
        storage = _make_storage()
        await storage.aput("akey1", b"async hello")
        result = await storage.aget("akey1")
        assert result == b"async hello"

    @pytest.mark.asyncio
    async def test_aget_missing_key_returns_none(self):
        storage = _make_storage()
        result = await storage.aget("nonexistent-async")
        assert result is None

    @pytest.mark.asyncio
    async def test_aremove_deletes_key(self):
        storage = _make_storage()
        await storage.aput("akey2", b"async data")
        await storage.aremove("akey2")
        result = await storage.aget("akey2")
        assert result is None

    @pytest.mark.asyncio
    async def test_attl_applied_on_aput(self):
        storage = _make_storage(ttl=60)
        await storage.aput("akey3", b"ttl-async-data")
        ttl = await storage._async_client.ttl("akey3")
        assert ttl > 0


class TestAsyncErrorWrapping:
    @pytest.mark.asyncio
    async def test_aget_redis_error_raises_storage_operation_error(self, monkeypatch):
        storage = _make_storage()

        async def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated async get error")

        monkeypatch.setattr(storage._async_client, "get", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aget("any-akey")

        error = exc_info.value
        assert error.operation == "aget"
        assert error.key == "any-akey"
        assert isinstance(error.__cause__, redis.RedisError)

    @pytest.mark.asyncio
    async def test_aput_redis_error_raises_storage_operation_error(self, monkeypatch):
        storage = _make_storage()

        async def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated async set error")

        monkeypatch.setattr(storage._async_client, "set", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aput("put-akey", b"payload")

        error = exc_info.value
        assert error.operation == "aput"
        assert error.key == "put-akey"
        assert isinstance(error.__cause__, redis.RedisError)

    @pytest.mark.asyncio
    async def test_aremove_redis_error_raises_storage_operation_error(
        self, monkeypatch
    ):
        storage = _make_storage()

        async def raise_redis_error(*args, **kwargs):
            raise redis.RedisError("simulated async delete error")

        monkeypatch.setattr(storage._async_client, "delete", raise_redis_error)

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aremove("del-akey")

        error = exc_info.value
        assert error.operation == "aremove"
        assert error.key == "del-akey"
        assert isinstance(error.__cause__, redis.RedisError)
