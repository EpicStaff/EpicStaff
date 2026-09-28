import functools

from django.conf import settings
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.s3_backend import S3StorageBackend


@functools.cache
def get_storage_manager() -> "StorageManager":  # noqa: F821
    """
    Return the singleton StorageManager backed by the prefix-free backend.

    The manager handles all org-path composition itself. Singleton is safe
    because the manager holds no per-request state — org_id is always passed
    as an argument.
    """
    from tables.services.storage_service.manager import StorageManager

    return StorageManager(get_storage_backend())


@functools.cache
def get_storage_backend() -> AbstractStorageBackend:
    """Return the one S3-compatible storage backend of this process. It has no
    organization prefix: keys carry their "org_<id>/" themselves."""
    return S3StorageBackend(
        endpoint_url=settings.STORAGE_ENDPOINT or None,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
        bucket_name=settings.STORAGE_BUCKET_NAME,
        organization_prefix="",
        part_size=settings.UPLOAD_PART_SIZE,
    )
