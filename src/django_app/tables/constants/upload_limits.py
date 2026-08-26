import os
from dataclasses import dataclass


# nginx caps a request body at 50M (nginx/templates/default.conf.template);
# the batch total is aligned with it so the API rejects with a readable 400
# instead of nginx dropping the connection.
DEFAULT_MAX_UPLOAD_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_UPLOAD_TOTAL_BYTES = 50 * 1024 * 1024

# Archive expansion. Real zip bombs run 900:1 and up; ordinary XML-heavy
# documents (DOCX, XLSX) sit well under 50:1, so 200:1 separates them safely.
DEFAULT_MAX_ARCHIVE_ENTRIES = 2_000
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_EXPANSION_RATIO = 200


@dataclass(frozen=True, kw_only=True)
class UploadLimits:
    """Caps applied to one upload request and to the archives inside it."""

    max_file_bytes: int
    max_total_bytes: int
    max_archive_entries: int
    max_archive_uncompressed_bytes: int
    max_archive_expansion_ratio: int


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to default."""
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


def default_upload_limits() -> UploadLimits:
    """Build the limits applied to uploads that do not supply their own."""
    return UploadLimits(
        max_file_bytes=_env_int("MAX_UPLOAD_FILE_BYTES", DEFAULT_MAX_UPLOAD_FILE_BYTES),
        max_total_bytes=_env_int(
            "MAX_UPLOAD_TOTAL_BYTES", DEFAULT_MAX_UPLOAD_TOTAL_BYTES
        ),
        max_archive_entries=_env_int(
            "MAX_ARCHIVE_ENTRIES", DEFAULT_MAX_ARCHIVE_ENTRIES
        ),
        max_archive_uncompressed_bytes=_env_int(
            "MAX_ARCHIVE_UNCOMPRESSED_BYTES", DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES
        ),
        max_archive_expansion_ratio=_env_int(
            "MAX_ARCHIVE_EXPANSION_RATIO", DEFAULT_MAX_ARCHIVE_EXPANSION_RATIO
        ),
    )
