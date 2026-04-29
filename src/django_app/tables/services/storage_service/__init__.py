import os

from django.conf import settings

from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.local_backend import LocalStorageBackend
from tables.services.storage_service.s3_backend import S3StorageBackend

_storage_manager = None


def get_storage_manager() -> "StorageManager":  # noqa: F821
    """
    Return the singleton StorageManager backed by a prefix-free backend.

    The manager handles all org-path composition itself, so the backend is
    initialized with an empty organization_prefix. Singleton is safe because
    the manager holds no per-request state — user_name and org_id are always
    passed as arguments.
    """
    global _storage_manager
    if _storage_manager is None:
        from tables.services.storage_service.manager import StorageManager

        _storage_manager = StorageManager(get_storage_backend(organization_prefix=""))
    return _storage_manager


def get_storage_backend(organization_prefix: str = "org_1/") -> AbstractStorageBackend:
    """
    Return the configured storage backend scoped to the given organization prefix.

    Backend type is controlled by the STORAGE_BACKEND environment variable:
      - "s3"    — S3StorageBackend (works with MinIO and AWS S3)
      - "local" — LocalStorageBackend (local filesystem, for testing)
    """
    backend_type = os.getenv("STORAGE_BACKEND", "s3")

    if backend_type == "local":
        return LocalStorageBackend(
            root=settings.STORAGE_LOCAL_ROOT,
            organization_prefix=organization_prefix,
        )

    return S3StorageBackend(
        endpoint_url=settings.STORAGE_ENDPOINT or None,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
        bucket_name=settings.STORAGE_BUCKET_NAME,
        organization_prefix=organization_prefix,
    )
