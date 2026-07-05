import io
from unittest.mock import MagicMock, patch, call

import pytest
from minio.error import S3Error

from communication.errors import StorageOperationError
from communication.storages.minio_ import MinioStorage


def _make_s3_error(code: str, key: str = "test-key") -> S3Error:
    """Build a minimal S3Error without a real HTTP response."""
    response = MagicMock()
    response.status = 500
    return S3Error(
        response, code, "error message", f"/bucket/{key}", "req-id", "host-id"
    )


def _make_storage_with_mock(
    bucket_exists_return=True,
) -> tuple[MinioStorage, MagicMock]:
    """Construct MinioStorage with a fully mocked Minio client.

    Returns the storage instance and the mock client for assertion.
    """
    with patch("communication.storages.minio_.Minio") as MockMinio:
        mock_client = MagicMock()
        MockMinio.return_value = mock_client
        mock_client.bucket_exists.return_value = bucket_exists_return

        storage = MinioStorage(
            host="localhost",
            port=9000,
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="test-bucket",
        )
    # Detach from the context manager — client already set on the instance
    storage._client = mock_client
    return storage, mock_client


class TestBucketInit:
    def test_bucket_exists_skips_make_bucket(self):
        with patch("communication.storages.minio_.Minio") as MockMinio:
            mock_client = MagicMock()
            MockMinio.return_value = mock_client
            mock_client.bucket_exists.return_value = True

            MinioStorage("localhost", 9000, "k", "s", "bucket")

        mock_client.make_bucket.assert_not_called()

    def test_bucket_missing_calls_make_bucket(self):
        with patch("communication.storages.minio_.Minio") as MockMinio:
            mock_client = MagicMock()
            MockMinio.return_value = mock_client
            mock_client.bucket_exists.return_value = False

            MinioStorage("localhost", 9000, "k", "s", "bucket")

        mock_client.make_bucket.assert_called_once_with("bucket")


class TestPut:
    def test_put_calls_put_object_with_correct_args(self):
        storage, client = _make_storage_with_mock()
        payload = b"hello bytes"
        storage.put("obj-key", payload)

        client.put_object.assert_called_once()
        call_kwargs = client.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "test-bucket"
        assert call_kwargs["object_name"] == "obj-key"
        assert call_kwargs["length"] == len(payload)
        # data should be a BytesIO with the right content
        data_arg = call_kwargs["data"]
        assert isinstance(data_arg, io.BytesIO)
        assert data_arg.read() == payload

    def test_put_s3_error_raises_storage_operation_error(self):
        storage, client = _make_storage_with_mock()
        client.put_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.put("obj-key", b"data")

        error = exc_info.value
        assert error.operation == "put"
        assert error.key == "obj-key"
        assert isinstance(error.__cause__, S3Error)


class TestGet:
    def test_get_returns_response_bytes(self):
        storage, client = _make_storage_with_mock()
        expected = b"stored content"

        mock_response = MagicMock()
        mock_response.read.return_value = expected
        client.get_object.return_value = mock_response

        result = storage.get("obj-key")

        assert result == expected
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    def test_get_no_such_key_returns_none(self):
        storage, client = _make_storage_with_mock()
        client.get_object.side_effect = _make_s3_error("NoSuchKey")

        result = storage.get("missing-key")

        assert result is None

    def test_get_other_s3_error_raises_storage_operation_error(self):
        storage, client = _make_storage_with_mock()
        client.get_object.side_effect = _make_s3_error("AccessDenied", "restricted-key")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.get("restricted-key")

        error = exc_info.value
        assert error.operation == "get"
        assert error.key == "restricted-key"
        assert isinstance(error.__cause__, S3Error)


class TestRemove:
    def test_remove_calls_remove_object(self):
        storage, client = _make_storage_with_mock()
        storage.remove("del-key")

        client.remove_object.assert_called_once_with(
            bucket_name="test-bucket",
            object_name="del-key",
        )

    def test_remove_s3_error_raises_storage_operation_error(self):
        storage, client = _make_storage_with_mock()
        client.remove_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            storage.remove("del-key")

        error = exc_info.value
        assert error.operation == "remove"
        assert error.key == "del-key"
        assert isinstance(error.__cause__, S3Error)


class TestAsyncDelegation:
    @pytest.mark.asyncio
    async def test_aput_delegates_to_put(self):
        storage, client = _make_storage_with_mock()
        payload = b"async bytes"
        await storage.aput("akey", payload)

        client.put_object.assert_called_once()
        call_kwargs = client.put_object.call_args.kwargs
        assert call_kwargs["bucket_name"] == "test-bucket"
        assert call_kwargs["object_name"] == "akey"

    @pytest.mark.asyncio
    async def test_aget_delegates_to_get(self):
        storage, client = _make_storage_with_mock()
        expected = b"async stored"
        mock_response = MagicMock()
        mock_response.read.return_value = expected
        client.get_object.return_value = mock_response

        result = await storage.aget("akey")
        assert result == expected

    @pytest.mark.asyncio
    async def test_aget_no_such_key_returns_none(self):
        storage, client = _make_storage_with_mock()
        client.get_object.side_effect = _make_s3_error("NoSuchKey")

        result = await storage.aget("missing-akey")
        assert result is None

    @pytest.mark.asyncio
    async def test_aremove_delegates_to_remove(self):
        storage, client = _make_storage_with_mock()
        await storage.aremove("adel-key")

        client.remove_object.assert_called_once_with(
            bucket_name="test-bucket",
            object_name="adel-key",
        )

    @pytest.mark.asyncio
    async def test_aput_s3_error_raises_storage_operation_error(self):
        storage, client = _make_storage_with_mock()
        client.put_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aput("akey", b"data")

        assert exc_info.value.operation == "put"

    @pytest.mark.asyncio
    async def test_aremove_s3_error_raises_storage_operation_error(self):
        storage, client = _make_storage_with_mock()
        client.remove_object.side_effect = _make_s3_error("InternalError")

        with pytest.raises(StorageOperationError) as exc_info:
            await storage.aremove("adel-key")

        assert exc_info.value.operation == "remove"
