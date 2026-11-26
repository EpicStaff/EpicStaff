import hashlib
from collections.abc import Iterable
from functools import cache
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from foundation.s3_file_storage import S3Bucket, S3FileStorage, S3ObjectNotExistError
from foundation.s3_file_storage.errors import S3FileStorageError, S3UnavailableError
from loguru import logger
from tables.exceptions import DocumentContentMissingException, StorageUnavailable
from tables.models import DocumentContent

DOCUMENTS_PREFIX = "documents"


@cache
def knowledge_bucket() -> S3Bucket:
    """Return this process's handle to the knowledge bucket; every call shares one boto3 client."""
    return S3FileStorage(
        host=settings.STORAGE_HOST,
        port=settings.STORAGE_PORT,
        user=settings.STORAGE_ACCESS_KEY,
        password=settings.STORAGE_SECRET_KEY,
        use_ssl=settings.STORAGE_SSL,
    ).bucket(settings.KNOWLEDGE_STORAGE_BUCKET)


def new_object_key(org_id: int) -> str:
    """Return a key no stored file has yet, in the organization's folder of `documents/`."""
    return f"{DOCUMENTS_PREFIX}/org_{org_id}/{uuid4().hex}"


class DocumentContentStorage:
    """Write, read and delete the stored files `DocumentContent.object_key` points at.

    A file is written before the row that points at it is committed and deleted after the
    rows that pointed at it are, so a failure in between leaves an unreferenced file, never
    a row pointing at nothing.
    """

    @staticmethod
    def write(org_id: int, data: bytes) -> str:
        """Store `data` under a new key and return the key.

        Raises:
            StorageUnavailable: Object storage could not be reached.
        """
        object_key = new_object_key(org_id)
        try:
            knowledge_bucket().object(object_key).write(data)
        except S3UnavailableError as error:
            raise StorageUnavailable() from error
        return object_key

    @staticmethod
    def create(org_id: int, data: bytes) -> DocumentContent:
        """Store `data` and create the content row pointing at it, with the bytes' SHA-256.

        If the row cannot be created, the file just written is deleted again.

        Raises:
            StorageUnavailable: Object storage could not be reached.
        """
        object_key = DocumentContentStorage.write(org_id, data)
        try:
            return DocumentContent.objects.create(
                object_key=object_key, content_hash=hashlib.sha256(data).hexdigest()
            )
        except Exception:
            DocumentContentStorage.delete([object_key])
            raise

    @staticmethod
    def read(object_key: str) -> bytes:
        """Return the stored file's bytes.

        Raises:
            DocumentContentMissingException: No file is stored under `object_key`.
            StorageUnavailable: Object storage could not be reached.
        """
        try:
            return knowledge_bucket().object(object_key).read()
        except S3ObjectNotExistError as error:
            raise DocumentContentMissingException() from error
        except S3UnavailableError as error:
            raise StorageUnavailable() from error

    @staticmethod
    def exists(object_key: str) -> bool:
        """Return whether a file is stored under `object_key`.

        Raises:
            StorageUnavailable: Object storage could not be reached.
        """
        try:
            return knowledge_bucket().object(object_key).exist()
        except S3UnavailableError as error:
            raise StorageUnavailable() from error

    @staticmethod
    def delete_unreferenced_rows(content_ids: Iterable[int]) -> list[str]:
        """Delete the rows among `content_ids` no document refers to and return their keys.

        The rows are locked before the references are counted. A copy of a document that
        points at one of them either committed before the count and keeps the row, or its
        foreign-key check waits for the lock and then fails: a deleted row's file is never
        still referenced. Deleting the returned files is the caller's choice of moment.
        Must run inside a transaction.
        """
        ids = list(content_ids)
        if not ids:
            return []
        locked_ids = list(
            DocumentContent.objects.select_for_update()
            .filter(id__in=ids)
            .values_list("id", flat=True)
        )
        unreferenced = dict(
            DocumentContent.objects.filter(id__in=locked_ids)
            .annotate(reference_count=Count("metadata_records"))
            .filter(reference_count=0)
            .values_list("id", "object_key")
        )
        DocumentContent.objects.filter(id__in=unreferenced).delete()
        return list(unreferenced.values())

    @staticmethod
    def delete(object_keys: Iterable[str]) -> None:
        """Delete the stored files now.

        A failure is logged, not raised: the rows that pointed at the files are already
        gone, so a file left behind only takes space.
        """
        keys = list(object_keys)
        if not keys:
            return
        try:
            knowledge_bucket().delete_objects(keys)
        except S3FileStorageError as error:
            logger.error("Could not delete {} stored document file(s): {}", len(keys), error)

    @staticmethod
    def delete_on_commit(object_keys: Iterable[str]) -> None:
        """Delete the stored files once the current transaction commits, and keep them if it rolls back."""
        keys = list(object_keys)
        if keys:
            transaction.on_commit(lambda: DocumentContentStorage.delete(keys))
