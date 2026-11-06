"""Storage of transfer-job archives, outside every organization's files and quota."""

from collections.abc import Iterator
from typing import BinaryIO
from uuid import UUID

from tables.services.storage_service import get_storage_backend

TRANSFERS_PREFIX = "system/transfers/"
_DEFAULT_CHUNK_SIZE = 1 << 20


class TransferArchiveStore:
    """Keep each job's archive under `system/transfers/<job id>/` in the storage bucket.

    Archives can be large, so they are never held whole in memory: uploads go
    part by part and reads come back in chunks.
    """

    def __init__(self, backend=None):
        # No organization prefix: transfer archives belong to no organization's files.
        self._backend = (
            backend if backend is not None else get_storage_backend(organization_prefix="")
        )

    @staticmethod
    def _job_prefix(job_id: UUID) -> str:
        return f"{TRANSFERS_PREFIX}{job_id}/"

    def upload_file(self, job_id: UUID, name: str, source: BinaryIO) -> str:
        """Store `source` as the job's archive `name`; returns its storage key."""
        key = f"{self._job_prefix(job_id)}{name}"
        self._backend.upload_stream(key, source)
        return key

    def iter_chunks(self, key: str, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """Yield the archive at `key` in chunks of at most `chunk_size` bytes."""
        return self._backend.iter_object(key, chunk_size)

    def download_to(self, key: str, destination: BinaryIO) -> None:
        """Write the archive at `key` into `destination`, one chunk at a time."""
        destination.writelines(self.iter_chunks(key))

    def delete_job(self, job_id: UUID) -> None:
        """Delete everything stored for the job; nothing to delete is fine."""
        self._backend.delete_prefix(self._job_prefix(job_id))
