from application.ports.document_content_reader import AbstractDocumentContentReader
from domain.errors import ContentStorageUnavailableError, DocumentContentMissingError
from foundation.s3_file_storage import S3Bucket, S3ObjectNotExistError
from foundation.s3_file_storage.errors import S3UnavailableError


class S3DocumentContentReader(AbstractDocumentContentReader):
    """Reads document files from the knowledge bucket of object storage."""

    def __init__(self, bucket: S3Bucket):
        self._bucket = bucket

    async def read(self, content_key: str) -> bytes:
        try:
            return await self._bucket.object(content_key).aread()
        except S3ObjectNotExistError as error:
            raise DocumentContentMissingError(documents=f"'{content_key}'") from error
        except S3UnavailableError as error:
            raise ContentStorageUnavailableError() from error
