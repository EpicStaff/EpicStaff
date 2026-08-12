import asyncio
import io
import re
from collections.abc import Coroutine, Iterator
from contextlib import asynccontextmanager
from typing import Any

from settings import settings
from graphrag_storage import Storage, StorageConfig, register_storage
from graphrag_storage.storage import get_timestamp_formatted_with_local_tz
from miniopy_async import Minio, S3Error
from miniopy_async.deleteobjects import DeleteObject


def create_storage_config(
    rag_id: int,
    subdir: str,
) -> StorageConfig:
    return StorageConfig(
        type="minio",
        prefix=f"graphrag/rag_{rag_id}/{subdir}",
        host=settings.MINIO_HOST,
        bucket=settings.MINIO_BUCKET,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        encoding=settings.GRAPHRAG_ENCODING,
    )


def _run_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = asyncio.get_running_loop()
    return loop.run_until_complete(coro)


class MinioStorage(Storage):
    _MISSING_CODES = frozenset(("NoSuchKey", "NoSuchObject", "NoSuchBucket"))

    def __init__(
        self,
        host: str,
        bucket: str,
        prefix: str,
        encoding: str,
        access_key: str,
        secret_key: str,
        **kwargs: Any,
    ) -> None:
        self._host = host
        self._bucket = bucket
        self._prefix = prefix
        self._encoding = encoding
        self._access_key = access_key
        self._secret_key = secret_key

        secure, endpoint = self._parse_host(self._host)
        self._client: Minio = Minio(
            endpoint=endpoint,
            secure=secure,
            access_key=self._access_key,
            secret_key=self._secret_key,
        )

    @asynccontextmanager
    async def _client_manager(self):
        if not await self._client.bucket_exists(self._bucket):
            await self._client.make_bucket(self._bucket)
        yield self._client
        await self._client.close_session()

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def _list_prefix(self) -> str:
        return f"{self._prefix}/"

    def _strip_prefix(self, object_name: str) -> str:
        listing = self._list_prefix()
        if object_name.startswith(listing):
            return object_name[len(listing) :]
        return object_name

    @staticmethod
    def _parse_host(host: str):
        protocol, endpoint = host.split("//")
        return protocol == "https", endpoint

    def find(self, file_pattern: re.Pattern[str]) -> Iterator[str]:
        async def _collect() -> list[str]:
            matches: list[str] = []
            async with self._client_manager() as client:
                async for obj in client.list_objects(
                    bucket_name=self._bucket,
                    prefix=self._list_prefix(),
                    recursive=True,
                ):
                    name = obj.object_name
                    if name and not obj.is_dir and file_pattern.search(name):
                        matches.append(self._strip_prefix(name))
                return matches

        return iter(_run_sync(_collect()))

    async def get(self, key: str, as_bytes: bool | None = None, encoding: str | None = None) -> Any:
        async with self._client_manager() as client:
            try:
                response = await client.get_object(
                    bucket_name=self._bucket,
                    object_name=self._full_key(key),
                )
            except S3Error as e:
                if e.code in self._MISSING_CODES:
                    return None
                raise
            else:
                data = await response.read()
            if as_bytes:
                return data
            return data.decode(encoding or self._encoding)

    async def set(self, key: str, value: Any, encoding: str | None = None) -> None:
        data = value if isinstance(value, bytes) else value.encode(encoding or self._encoding)

        async with self._client_manager() as client:
            await client.put_object(
                bucket_name=self._bucket,
                object_name=self._full_key(key),
                data=io.BytesIO(data),
                length=len(data),
                content_type="application/octet-stream",
            )

    async def has(self, key: str) -> bool:
        async with self._client_manager() as client:
            try:
                await client.stat_object(
                    bucket_name=self._bucket,
                    object_name=self._full_key(key),
                )
            except S3Error as e:
                if e.code in self._MISSING_CODES:
                    return False
                raise
            return True

    async def delete(self, key: str) -> None:
        async with self._client_manager() as client:
            await client.remove_object(
                bucket_name=self._bucket,
                object_name=self._full_key(key),
            )

    async def clear(self) -> None:
        async with self._client_manager() as client:
            objects = await client.list_objects(
                bucket_name=self._bucket,
                prefix=self._list_prefix(),
                recursive=True,
            )
            delete_list = [DeleteObject(o.object_name) for o in objects]
            if not delete_list:
                return
            await client.remove_objects(
                bucket_name=self._bucket,
                delete_object_list=delete_list,
            )

    def child(self, name: str | None) -> "Storage":
        if name is None:
            return self

        return MinioStorage(
            host=self._host,
            bucket=self._bucket,
            prefix=self._full_key(name),
            encoding=self._encoding,
            access_key=self._access_key,
            secret_key=self._secret_key,
        )

    def keys(self) -> list[str]:
        async def _collect() -> list[str]:
            async with self._client_manager() as client:
                objects = await client.list_objects(
                    bucket_name=self._bucket,
                    prefix=self._list_prefix(),
                    recursive=True,
                )
                return [
                    self._strip_prefix(obj.object_name)
                    for obj in objects
                    if obj.object_name and not obj.is_dir
                ]

        return _run_sync(_collect())

    async def get_creation_date(self, key: str) -> str:
        async with self._client_manager() as client:
            try:
                stat = await client.stat_object(
                    bucket_name=self._bucket,
                    object_name=self._full_key(key),
                )
            except S3Error as e:
                if e.code in self._MISSING_CODES:
                    return ""
                raise
        return get_timestamp_formatted_with_local_tz(stat.last_modified)


register_storage("minio", MinioStorage)
