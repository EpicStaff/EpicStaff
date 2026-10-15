from django.conf import settings
from tables.services.storage_service.archive_unpacking.names import (
    ARCHIVE_SUFFIXES,
    DOCUMENT_EXTENSIONS,
)
from tables.services.storage_service.quota import org_free_bytes


def upload_limits(org_id: int) -> dict:
    """The limits the streaming upload enforces for this org, so a client can skip a doomed file."""
    return {
        "max_file_size": settings.MAX_STREAM_UPLOAD_FILE_SIZE,
        "max_archive_size": settings.MAX_ARCHIVE_FILE_SIZE,
        "free_bytes": org_free_bytes(org_id),
        "archive_suffixes": sorted(ARCHIVE_SUFFIXES),
        "document_extensions": sorted(DOCUMENT_EXTENSIONS),
    }
