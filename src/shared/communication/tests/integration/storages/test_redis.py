import time

import pytest

pytestmark = pytest.mark.integration

from communication.storages.redis_ import RedisStorage


@pytest.fixture
def storage(redis_url):
    return RedisStorage(redis_url, ttl=10)


class TestSyncRoundtrip:
    def test_put_get_roundtrip_returns_exact_bytes(self, storage):
        payload = b"integration test payload"
        storage.put("integ-key-1", payload)
        result = storage.get("integ-key-1")
        assert result == payload

    def test_get_missing_key_returns_none(self, storage):
        result = storage.get("definitely-does-not-exist-12345")
        assert result is None

    def test_remove_deletes_key(self, storage):
        storage.put("integ-key-del", b"to be deleted")
        storage.remove("integ-key-del")
        assert storage.get("integ-key-del") is None

    def test_ttl_expiry(self, redis_url):
        """Key with a very short TTL should expire and return None."""
        storage = RedisStorage(redis_url, ttl=1)
        storage.put("expiring-key", b"will expire")
        time.sleep(1.5)
        result = storage.get("expiring-key")
        assert result is None


class TestAsyncRoundtrip:
    @pytest.mark.asyncio
    async def test_aput_aget_roundtrip_returns_exact_bytes(self, storage):
        payload = b"async integration payload"
        await storage.aput("ainteg-key-1", payload)
        result = await storage.aget("ainteg-key-1")
        assert result == payload

    @pytest.mark.asyncio
    async def test_aget_missing_key_returns_none(self, storage):
        result = await storage.aget("async-definitely-missing-99999")
        assert result is None

    @pytest.mark.asyncio
    async def test_aremove_deletes_key(self, storage):
        await storage.aput("ainteg-key-del", b"async to be deleted")
        await storage.aremove("ainteg-key-del")
        result = await storage.aget("ainteg-key-del")
        assert result is None
