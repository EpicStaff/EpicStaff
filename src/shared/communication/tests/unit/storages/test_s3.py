import io
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

from communication.errors import StorageOperationError
from communication.storages.s3_storage import S3Storage


def _make_s3_error(code: str, key: str = "test-key") -> S3Error:
    """Build a minimal S3Error without a real HTTP response."""
    response = MagicMock()
    response.status = 500
    return S3Error(
        response, code, "error message", f"/bucket/{key}", "req-id", "host-id"
    )


@contextmanager
def _patched_s3(bucket_exists: bool = True):
    """Patch the lazily-imported `minio` module with a mock client.

    `S3Storage` reads `minio.Minio` and `minio.S3Error` from a module-level
    global at call time, so the patch must stay active for the whole `with`
    block — including during put/get/remove. Yields the mock Minio client.
    """
    fake_s3 = MagicMock()
    fake_s3.S3Error = S3Error  # real class so `except` / handle_error work
    client = MagicMock()
    client.bucket_exists.return_value = bucket_exists
    fake_s3.Minio.return_value = client
    with patch("communication.storages.s3_storage.minio", fake_s3):
        yield client


@pytest.fixture
def storage_and_client():
    """S3Storage backed by a mock client, with the `minio` patch held active."""
    with _patched_s3() as client:
        storage = S3Storage(
            host="localhost",
            port=9000,
            access_key="storageadmin",
            secret_key="storageadmin",
            bucket="test-bucket",
        )
        yield storage, client


class TestBucketInit:
    def test_bucket_exists_skips_make_bucket(self):
        with _patched_s3(bucket_exists=True) as client:
            S3Storage("localhost", 9000, "k", "s", "bucket")

        client.make_bucket.assert_not_called()

    def test_bucket_missing_calls_make_bucket(self):
        with _patched_s3(bucket_exists=False) as client:
            S3Storage("localhost", 9000, "k", "s", "bucket")

        client.make_bucket.assert_called_once_with("bucket")


class TestPut:
    def test_put_calls_put_object_with_correct_args(self, storage_and_client):
        storage, client = storage_and_client
        payload = b"hello bytes"
        storage.put("obj-key", payload)

        client.put_object.assert_called_once()
        call_kwargs = client.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "test-bucket"
        assert call_kwargs["object_name"] == "obj-key"
        assert call_kwargs["length"] == len(payload)
        data_arg = call_kwargs["data"]
        assert isinstance(data_arg, io.BytesIO)
        assert data_arg.read() == payload

    def test_put_s3_error_raises_storage_operation_error(self, storage_and_client):
        storage, client = storage_and_client
        client.put_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.put("obj-key", b"data")

        error = exc_info.value
        assert error.operation == "put"
        assert error.key == "obj-key"
        assert isinstance(error.__cause__, S3Error)


class TestGet:
    def test_get_returns_response_bytes(self, storage_and_client):
        storage, client = storage_and_client
        expected = b"stored content"

        mock_response = MagicMock()
        mock_response.read.return_value = expected
        client.get_object.return_value = mock_response

        result = storage.get("obj-key")

        assert result == expected
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    def test_get_no_such_key_returns_none(self, storage_and_client):
        storage, client = storage_and_client
        client.get_object.side_effect = _make_s3_error("NoSuchKey")

        result = storage.get("missing-key")

        assert result is None

    def test_get_other_s3_error_raises_storage_operation_error(
        self, storage_and_client
    ):
        storage, client = storage_and_client
        client.get_object.side_effect = _make_s3_error("AccessDenied", "restricted-key")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.get("restricted-key")

        error = exc_info.value
        assert error.operation == "get"
        assert error.key == "restricted-key"
        assert isinstance(error.__cause__, S3Error)


class TestRemove:
    def test_remove_calls_remove_object(self, storage_and_client):
        storage, client = storage_and_client
        storage.remove("del-key")

        client.remove_object.assert_called_once_with(
            bucket_name="test-bucket",
            object_name="del-key",
        )

    def test_remove_s3_error_raises_storage_operation_error(self, storage_and_client):
        storage, client = storage_and_client
        client.remove_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.remove("del-key")

        error = exc_info.value
        assert error.operation == "remove"
        assert error.key == "del-key"
        assert isinstance(error.__cause__, S3Error)


class TestAsyncDelegation:
    @pytest.mark.asyncio
    async def test_aput_delegates_to_put(self, storage_and_client):
        storage, client = storage_and_client
        payload = b"async bytes"
        await storage.aput("akey", payload)

        client.put_object.assert_called_once()
        call_kwargs = client.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "test-bucket"
        assert call_kwargs["object_name"] == "akey"

    @pytest.mark.asyncio
    async def test_aget_delegates_to_get(self, storage_and_client):
        storage, client = storage_and_client
        expected = b"async stored"
        mock_response = MagicMock()
        mock_response.read.return_value = expected
        client.get_object.return_value = mock_response

        result = await storage.aget("akey")
        assert result == expected

    @pytest.mark.asyncio
    async def test_aget_no_such_key_returns_none(self, storage_and_client):
        storage, client = storage_and_client
        client.get_object.side_effect = _make_s3_error("NoSuchKey")

        result = await storage.aget("missing-akey")
        assert result is None

    @pytest.mark.asyncio
    async def test_aremove_delegates_to_remove(self, storage_and_client):
        storage, client = storage_and_client
        await storage.aremove("adel-key")

        client.remove_object.assert_called_once_with(
            bucket_name="test-bucket",
            object_name="adel-key",
        )

    @pytest.mark.asyncio
    async def test_aput_s3_error_raises_storage_operation_error(
        self, storage_and_client
    ):
        storage, client = storage_and_client
        client.put_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aput("akey", b"data")

        assert exc_info.value.operation == "put"

    @pytest.mark.asyncio
    async def test_aremove_s3_error_raises_storage_operation_error(
        self, storage_and_client
    ):
        storage, client = storage_and_client
        client.remove_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aremove("adel-key")

        assert exc_info.value.operation == "remove"
