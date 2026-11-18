from collections.abc import AsyncIterator
from typing import BinaryIO

from application.ports.artifact_store import AbstractArtifactStore, StoredObject
from domain.errors import ArtifactStorageError
from infrastructure.graphrag.s3_client import open_s3_client
from loguru import logger
from miniopy_async.deleteobjects import DeleteObject

# 1 MiB of an object held in memory at a time while it is streamed.
_DOWNLOAD_CHUNK_SIZE = 1 << 20


class S3ArtifactStore(AbstractArtifactStore):
    """An artifact store that uses S3 as the backend."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        self._endpoint = endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key

    async def list_objects(self, prefix: str) -> list[StoredObject]:
        """List objects in the S3 bucket under the given prefix."""
        async with open_s3_client(
            endpoint=self._endpoint,
            bucket=self._bucket,
            access_key=self._access_key,
            secret_key=self._secret_key,
        ) as client:
            listed_objects = []
            async for obj in client.list_objects(
                bucket_name=self._bucket,
                prefix=prefix,
                recursive=True,
            ):
                if obj.is_dir:
                    continue
                listed_objects.append(StoredObject(key=obj.object_name, size=obj.size))
        return listed_objects

    async def iter_object(self, key: str) -> AsyncIterator[bytes]:
        """Yield the bytes of the object at `key` in chunks."""
        async with open_s3_client(
            endpoint=self._endpoint,
            bucket=self._bucket,
            access_key=self._access_key,
            secret_key=self._secret_key,
        ) as client:
            response = await client.get_object(bucket_name=self._bucket, object_name=key)
            try:
                async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_SIZE):
                    yield chunk
            finally:
                response.release()

    async def put(self, key: str, source: BinaryIO, size: int) -> None:
        async with open_s3_client(
            endpoint=self._endpoint,
            bucket=self._bucket,
            access_key=self._access_key,
            secret_key=self._secret_key,
        ) as client:
            await client.put_object(
                bucket_name=self._bucket, object_name=key, data=source, length=size
            )

    async def clear(self, prefix: str) -> None:
        objects = await self.list_objects(prefix)
        if not objects:
            return

        async with open_s3_client(
            endpoint=self._endpoint,
            bucket=self._bucket,
            access_key=self._access_key,
            secret_key=self._secret_key,
        ) as client:
            # Awaiting runs the deletes (in batches of 1000) and collects the keys that failed.
            errors = await client.remove_objects(
                self._bucket, [DeleteObject(stored.key) for stored in objects]
            )
        if errors:
            for error in errors:
                logger.error(
                    "Could not delete {} from the artifact store: {}", error.name, error.message
                )
            raise ArtifactStorageError(failed_count=len(errors), prefix=prefix)
