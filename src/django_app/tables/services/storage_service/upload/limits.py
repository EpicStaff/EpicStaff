from django.conf import settings
from tables.services.storage_service.archive.names import ARCHIVE_SUFFIXES, DOCUMENT_EXTENSIONS
from tables.services.storage_service.quota import org_free_bytes


def upload_limits(org_id: int) -> dict:
    """What the streaming upload will enforce for this org, so a client can skip a
    doomed file before sending it. A name is routed as an archive iff it ends with
    an archive suffix and not with a document extension (is_archive_name).
    `free_bytes` ignores uploads still running and credits no file an upload
    would overwrite."""
    return {
        "max_file_size": settings.MAX_STREAM_UPLOAD_FILE_SIZE,
        "max_archive_size": settings.MAX_ARCHIVE_FILE_SIZE,
        "free_bytes": org_free_bytes(org_id),
        "archive_suffixes": sorted(ARCHIVE_SUFFIXES),
        "document_extensions": sorted(DOCUMENT_EXTENSIONS),
    }
