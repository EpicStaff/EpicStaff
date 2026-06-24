import asyncio
import io

from minio import Minio, S3Error

from communication.errors import StorageOperationError
from communication.error_handler import handle_error
from communication.storages.abstract import AbstractStorage


class MinioStorage(AbstractStorage):
    """MinIO implementation of storage.

    Args:
        host: MinIO server hostname or IP address.
        port: MinIO server port.
        access_key: MinIO access key (username).
        secret_key: MinIO secret key (password).
        bucket: Bucket name to store objects in. Created automatically if it
            does not exist.
        secure: Whether to use TLS. Defaults to ``False``.

    """

    def __init__(
        self,
        host: str,
        port: int,
        access_key: str,
        secret_key: str,
        bucket: str,
        *,
        secure=False,
    ):
        self._client = Minio(
            endpoint=f"{host}:{port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket

        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, key: str, payload: bytes):
        with handle_error(S3Error, StorageOperationError, "put", key):
            self._client.put_object(
                bucket_name=self._bucket,
                object_name=key,
                data=io.BytesIO(payload),
                length=len(payload),
            )

    async def aput(self, key: str, payload: bytes):
        return await asyncio.to_thread(self.put, key, payload)

    def get(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(
                bucket_name=self._bucket,
                object_name=key,
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise StorageOperationError("get", key) from e

    async def aget(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self.get, key)

    def remove(self, key: str):
        with handle_error(S3Error, StorageOperationError, "remove", key):
            self._client.remove_object(
                bucket_name=self._bucket,
                object_name=key,
            )

    async def aremove(self, key: str):
        return await asyncio.to_thread(self.remove, key)
