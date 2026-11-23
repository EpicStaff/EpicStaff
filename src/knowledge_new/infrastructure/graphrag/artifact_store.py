from collections.abc import AsyncIterator
from typing import BinaryIO

from application.ports.artifact_store import AbstractArtifactStore, StoredObject
from domain.errors import ArtifactStorageError
from foundation.s3_file_storage import S3Bucket, S3ObjectError
from foundation.utils import humanize
from loguru import logger

# Bytes of an object held in memory at a time while it is streamed.
_DOWNLOAD_CHUNK_SIZE = humanize.to_byte_size("1mb")


class S3ArtifactStore(AbstractArtifactStore):
    """An artifact store that uses S3 as the backend."""

    def __init__(self, bucket: S3Bucket) -> None:
        self._bucket = bucket

    async def list_objects(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(key=stored.key, size=stored.size)
            for stored in await self._bucket.aobjects(prefix=prefix)
        ]

    async def iter_object(self, key: str) -> AsyncIterator[bytes]:
        async for chunk in self._bucket.object(key).aiter_chunks(_DOWNLOAD_CHUNK_SIZE):
            yield chunk

    async def put(self, key: str, source: BinaryIO, size: int) -> None:
        # boto3 sends the stream in parts and needs no length up front, so `size` goes unused.
        await self._bucket.object(key).aupload(source)

    async def clear(self, prefix: str) -> None:
        objects = await self.list_objects(prefix)
        if not objects:
            return
        try:
            await self._bucket.adelete_objects(stored.key for stored in objects)
        except S3ObjectError as error:
            logger.error("Could not clear '{}' in the artifact store: {}", prefix, error)
            raise ArtifactStorageError(
                f"Could not delete every object under '{prefix}': {error}"
            ) from error
