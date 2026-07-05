import uuid

import pytest

pytestmark = pytest.mark.integration

from communication.storages.minio_ import MinioStorage


@pytest.fixture
def storage(minio_params):
    bucket = f"test-bucket-{uuid.uuid4().hex[:8]}"
    return MinioStorage(
        host=minio_params["host"],
        port=minio_params["port"],
        access_key=minio_params["access_key"],
        secret_key=minio_params["secret_key"],
        bucket=bucket,
        secure=False,
    )


class TestSyncRoundtrip:
    def test_bucket_auto_created_on_init(self, minio_params):
        """MinioStorage creates the bucket automatically if it does not exist."""
        bucket = f"auto-bucket-{uuid.uuid4().hex[:8]}"
        s = MinioStorage(
            host=minio_params["host"],
            port=minio_params["port"],
            access_key=minio_params["access_key"],
            secret_key=minio_params["secret_key"],
            bucket=bucket,
            secure=False,
        )
        # Verify it can actually write — bucket must exist at this point
        s.put("probe", b"probe")
        assert s.get("probe") == b"probe"

    def test_put_get_roundtrip_returns_exact_bytes(self, storage):
        payload = b"minio integration payload"
        storage.put("obj-1", payload)
        result = storage.get("obj-1")
        assert result == payload

    def test_get_missing_key_returns_none(self, storage):
        result = storage.get("does-not-exist-key")
        assert result is None

    def test_remove_key(self, storage):
        storage.put("obj-del", b"to remove")
        storage.remove("obj-del")
        result = storage.get("obj-del")
        assert result is None


class TestAsyncRoundtrip:
    @pytest.mark.asyncio
    async def test_aput_aget_roundtrip_returns_exact_bytes(self, storage):
        payload = b"async minio payload"
        await storage.aput("aobj-1", payload)
        result = await storage.aget("aobj-1")
        assert result == payload

    @pytest.mark.asyncio
    async def test_aget_missing_key_returns_none(self, storage):
        result = await storage.aget("async-does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_aremove_key(self, storage):
        await storage.aput("aobj-del", b"async to remove")
        await storage.aremove("aobj-del")
        result = await storage.aget("aobj-del")
        assert result is None
