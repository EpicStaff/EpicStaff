from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True, kw_only=True)
class UploadLimits:
    """Caps applied to one upload request and to the archives inside it."""

    max_file_bytes: int
    max_total_bytes: int
    max_archive_entries: int
    max_archive_uncompressed_bytes: int


def default_upload_limits() -> UploadLimits:
    """Build the limits applied to uploads that do not supply their own."""
    return UploadLimits(
        max_file_bytes=settings.MAX_UPLOAD_FILE_SIZE,
        max_total_bytes=settings.MAX_UPLOAD_TOTAL_SIZE,
        max_archive_entries=settings.MAX_ARCHIVE_ENTRIES,
        max_archive_uncompressed_bytes=settings.MAX_ARCHIVE_UNCOMPRESSED_SIZE,
    )
