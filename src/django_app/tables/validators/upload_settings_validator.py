import re

from django.core.exceptions import ImproperlyConfigured
from src.shared import humanize

# S3 multipart limits: every part but the last must be at least 5 MiB, and one
# upload has at most 10,000 parts.
S3_MIN_PART_SIZE = 5 * 1024 * 1024
S3_MAX_PARTS = 10_000

# The subset of Go's time.ParseDuration syntax (what MinIO parses) that
# humanize.to_time reads the same way: one number and one lowercase s/m/h unit.
_GO_DURATION = re.compile(r"\d+(\.\d+)?(s|m|h)")


def parse_minio_duration(name: str, raw: str | None) -> float:
    """Seconds of a duration setting that MinIO reads too, e.g. "6h".

    Raises:
        ImproperlyConfigured: a value MinIO (Go time.ParseDuration) would reject or
            read differently, such as plain seconds, days, an upper-case unit or none.
    """
    if raw is None or not _GO_DURATION.fullmatch(raw):
        raise ImproperlyConfigured(
            f"{name} is {raw!r}; MinIO reads it as a Go duration, so use a number and "
            "one of the units s, m, h (e.g. 6h or 90m)."
        )
    return humanize.to_time(raw)


def validate_upload_settings(
    *,
    part_size: int,
    storage_quota: int,
    max_stream_file_size: int | None,
    max_archive_file_size: int | None,
    max_concurrency: int | None,
    per_org_limit: int | None,
    slot_timeout: float | None,
    idle_timeout: float | None,
    max_duration: float | None,
    stale_uploads_expiry: float,
) -> None:
    """Fail startup on streaming-upload settings that would break uploads at runtime.

    Imported by ``django_app.settings``, so this module must not import anything
    that needs the Django app registry.

    Raises:
        ImproperlyConfigured: a part below the S3 minimum; a quota that a single
            file cannot fill within 10,000 parts; a max streaming file size that
            is not positive (none means unlimited); a max archive size that is
            none or not positive; a concurrency limit or timeout
            that is none or not positive; a slot timeout that is not positive
            (none means wait forever); a per-org limit above the per-worker
            one; or a max upload duration that lets MinIO expire a still-running
            multipart upload.
    """
    if part_size < S3_MIN_PART_SIZE:
        raise ImproperlyConfigured(
            f"DJANGO_UPLOAD_PART_SIZE is {part_size} bytes; S3 requires at least "
            f"{S3_MIN_PART_SIZE} bytes (5mb) per multipart part."
        )
    if part_size * S3_MAX_PARTS < storage_quota:
        raise ImproperlyConfigured(
            f"DJANGO_UPLOAD_PART_SIZE ({part_size} bytes) x {S3_MAX_PARTS} S3 parts is "
            f"below DJANGO_ORG_STORAGE_QUOTA ({storage_quota} bytes): a file that fills "
            "the quota could not be uploaded. Raise the part size or lower the quota."
        )
    if max_stream_file_size is not None and max_stream_file_size <= 0:
        raise ImproperlyConfigured(
            f"DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE is {max_stream_file_size!r}; it must be a "
            "positive size, or none for unlimited."
        )
    if max_archive_file_size is None or max_archive_file_size <= 0:
        # No "unlimited" here: an archive is buffered whole before it is unpacked.
        raise ImproperlyConfigured(
            f"DJANGO_MAX_ARCHIVE_FILE_SIZE is {max_archive_file_size!r}; it must be a "
            "positive size, since the whole archive is buffered on the server."
        )
    if slot_timeout is not None and slot_timeout <= 0:
        raise ImproperlyConfigured(
            f"DJANGO_UPLOAD_SLOT_TIMEOUT is {slot_timeout!r}; it must be a positive "
            "time, or none to wait for a free slot forever."
        )
    for name, value in (
        ("DJANGO_UPLOAD_MAX_CONCURRENCY", max_concurrency),
        ("DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG", per_org_limit),
        ("DJANGO_UPLOAD_IDLE_TIMEOUT", idle_timeout),
        ("DJANGO_UPLOAD_MAX_DURATION", max_duration),
    ):
        if value is None or value <= 0:
            raise ImproperlyConfigured(f"{name} is {value!r}; it must be a positive value.")
    if per_org_limit > max_concurrency:
        raise ImproperlyConfigured(
            f"DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG ({per_org_limit}) is above "
            f"DJANGO_UPLOAD_MAX_CONCURRENCY ({max_concurrency}): the extra uploads would "
            "queue behind the organization's own and could time out with 503 instead of "
            "getting a 429 at once."
        )
    if max_duration >= stale_uploads_expiry:
        raise ImproperlyConfigured(
            f"DJANGO_UPLOAD_MAX_DURATION ({max_duration:g}s) must be below "
            f"MINIO_STALE_UPLOADS_EXPIRY ({stale_uploads_expiry:g}s), or MinIO drops the "
            "parts of an upload that is still running."
        )
