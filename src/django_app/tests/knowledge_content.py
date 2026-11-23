"""An in-memory knowledge bucket for tests, and helpers for stored document content.

The suite never reaches real object storage: the root conftest swaps the knowledge bucket
for `InMemoryKnowledgeBucket` in every test (fixture `knowledge_bucket`).
"""

from foundation.s3_file_storage import S3ObjectNotExistError
from tables.models import DocumentContent, DocumentMetadata
from tables.services.knowledge_services.document_content_storage import DocumentContentStorage


class InMemoryKnowledgeBucket:
    """The part of foundation's `S3Bucket` the app uses, holding files in a dict."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def object(self, key: str) -> "_InMemoryObject":
        return _InMemoryObject(self.files, key)

    def delete_objects(self, keys) -> None:
        for key in keys:
            self.files.pop(key, None)


class _InMemoryObject:
    def __init__(self, files: dict[str, bytes], key: str):
        self._files = files
        self.key = key

    def write(self, data: bytes) -> None:
        self._files[self.key] = bytes(data)

    def read(self) -> bytes:
        try:
            return self._files[self.key]
        except KeyError as error:
            raise S3ObjectNotExistError(
                "The specified key does not exist.", code="NoSuchKey", key=self.key
            ) from error

    def delete(self) -> None:
        self._files.pop(self.key, None)


def stored_document_content(data: bytes, *, org_id: int = 0) -> DocumentContent:
    """Store `data` in the test knowledge bucket and create the row pointing at it."""
    return DocumentContent.objects.create(object_key=DocumentContentStorage.write(org_id, data))


def stored_document_bytes(document: DocumentMetadata) -> bytes:
    """Return the bytes stored for `document`."""
    return DocumentContentStorage.read(document.document_content.object_key)
