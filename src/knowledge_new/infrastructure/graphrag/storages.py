import re
from collections.abc import Iterator
from typing import Any

import settings
from foundation.s3_file_storage import S3BucketNotExistError, S3ObjectNotExistError
from graphrag_storage import Storage, StorageConfig, register_storage
from graphrag_storage.storage import get_timestamp_formatted_with_local_tz
from infrastructure.graphrag.s3_bucket import open_bucket


def create_storage_config(
    rag_id: int,
    subdir: str | None = None,
) -> StorageConfig:
    prefix = f"graphrag/rag_{rag_id}"
    if subdir:
        prefix += f"/{subdir}"
    return StorageConfig(
        type="s3",
        prefix=prefix,
        endpoint=settings.STORAGE_ENDPOINT,
        bucket=settings.KNOWLEDGE_BUCKET,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
        encoding=settings.GRAPHRAG_ENCODING,
    )


class S3Storage(Storage):
    """graphrag's storage for one prefix of the knowledge bucket."""

    _MISSING = (S3ObjectNotExistError, S3BucketNotExistError)

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        prefix: str,
        encoding: str,
        access_key: str,
        secret_key: str,
        **kwargs: Any,
    ) -> None:
        self._connection = {
            "endpoint": endpoint,
            "bucket": bucket,
            "access_key": access_key,
            "secret_key": secret_key,
        }
        self._bucket = open_bucket(endpoint, bucket, access_key, secret_key)
        self._prefix = prefix
        self._encoding = encoding

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def _list_prefix(self) -> str:
        return f"{self._prefix}/"

    def _strip_prefix(self, object_name: str) -> str:
        listing = self._list_prefix()
        if object_name.startswith(listing):
            return object_name[len(listing) :]
        return object_name

    def find(self, file_pattern: re.Pattern[str]) -> Iterator[str]:
        keys = [stored.key for stored in self._bucket.objects(prefix=self._list_prefix())]
        return iter([self._strip_prefix(key) for key in keys if file_pattern.search(key)])

    async def get(self, key: str, as_bytes: bool | None = None, encoding: str | None = None) -> Any:
        try:
            data = await self._bucket.object(self._full_key(key)).aread()
        except self._MISSING:
            return None
        if as_bytes:
            return data
        return data.decode(encoding or self._encoding)

    async def set(self, key: str, value: Any, encoding: str | None = None) -> None:
        data = value if isinstance(value, bytes) else value.encode(encoding or self._encoding)
        await self._bucket.object(self._full_key(key)).awrite(data)

    async def has(self, key: str) -> bool:
        return await self._bucket.object(self._full_key(key)).aexist()

    async def delete(self, key: str) -> None:
        await self._bucket.object(self._full_key(key)).adelete()

    async def clear(self) -> None:
        stored = await self._bucket.aobjects(prefix=self._list_prefix())
        await self._bucket.adelete_objects(stored_object.key for stored_object in stored)

    def child(self, name: str | None) -> "Storage":
        if name is None:
            return self
        return S3Storage(**self._connection, prefix=self._full_key(name), encoding=self._encoding)

    def keys(self) -> list[str]:
        return [
            self._strip_prefix(stored.key)
            for stored in self._bucket.objects(prefix=self._list_prefix())
        ]

    async def get_creation_date(self, key: str) -> str:
        try:
            last_modified = await self._bucket.object(self._full_key(key)).alast_modified()
        except self._MISSING:
            return ""
        return get_timestamp_formatted_with_local_tz(last_modified)


register_storage("s3", S3Storage)
