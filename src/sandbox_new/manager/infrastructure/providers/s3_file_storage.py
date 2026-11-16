from typing import BinaryIO

from foundation.s3_file_storage import S3Bucket, S3ObjectNotExistError

from manager.application.ports import AbstractFileStorage

__all__ = ["FileStorage"]


class FileStorage(AbstractFileStorage):
    """`AbstractFileStorage` over one S3 bucket.

    Keeps the S3 vocabulary on this side of the port: the application sees keys,
    bytes and `FileNotFoundError`, never a bucket handle or a botocore error.
    """

    def __init__(self, bucket: S3Bucket):
        self._bucket = bucket

    async def put(self, key: str, file: BinaryIO):
        await self._bucket.object(key).aupload(file)

    async def get(self, key: str) -> bytes:
        """Return the whole object stored under `key`.

        Raises:
            FileNotFoundError: Nothing is stored under this key.
        """
        try:
            return await self._bucket.object(key).aread()
        except S3ObjectNotExistError as error:
            raise FileNotFoundError(key) from error

    async def delete(self, key: str):
        await self._bucket.object(key).adelete()
