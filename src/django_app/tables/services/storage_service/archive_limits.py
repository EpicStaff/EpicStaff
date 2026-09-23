from tables.constants.upload_limits import default_upload_limits


class ArchiveLimitExceeded(ValueError):  # noqa: N818
    """Raised when an archive expands past what one extraction is allowed to buffer."""


class ArchiveExtractionGuard:
    """Bounds one archive extraction in entry count and decompressed byte total."""

    CHUNK_BYTES = 1024 * 1024

    def __init__(self, *, max_entries: int, max_total_bytes: int):
        self.max_entries = max_entries
        self.max_total_bytes = max_total_bytes
        self.entries_seen = 0
        self.bytes_read = 0

    def account_entry(self) -> None:
        """Account one archive member, rejecting an archive with too many entries."""
        self.entries_seen += 1
        if self.entries_seen > self.max_entries:
            raise ArchiveLimitExceeded(f"Archive contains more than {self.max_entries} entries")

    def account_bytes(self, n: int, name: str) -> None:
        """Account n decompressed bytes as they stream, rejecting past the cap."""
        self.bytes_read += n
        if self.bytes_read > self.max_total_bytes:
            raise ArchiveLimitExceeded(
                f"Archive member '{name}' pushes the extraction past {self.max_total_bytes} bytes"
            )

    def read_member(self, member_file, name: str) -> bytes:
        """Read one member, stopping as soon as it would outgrow the remaining budget."""
        remaining = self.max_total_bytes - self.bytes_read
        parts: list[bytes] = []

        while True:
            chunk = member_file.read(min(self.CHUNK_BYTES, remaining + 1))
            if not chunk:
                break

            self.bytes_read += len(chunk)
            remaining -= len(chunk)
            if remaining < 0:
                raise ArchiveLimitExceeded(
                    f"Archive member '{name}' pushes the extraction past "
                    f"{self.max_total_bytes} bytes"
                )

            parts.append(chunk)

        return b"".join(parts)


class GuardedMemberReader:
    """File-like wrapper over one archive member; accrues guard bytes on read.

    The member is streamed to storage chunk-by-chunk (never buffered), so a
    zip-bomb member is rejected mid-read instead of after full extraction."""

    def __init__(self, member_file, guard: ArchiveExtractionGuard, name: str):
        self._f = member_file
        self._guard = guard
        self._name = name

    def read(self, size: int = -1) -> bytes:
        chunk = self._f.read(size)
        if chunk:
            self._guard.account_bytes(len(chunk), self._name)
        return chunk


def default_guard() -> ArchiveExtractionGuard:
    """Build the guard applied to extractions that do not supply one."""
    limits = default_upload_limits()
    return ArchiveExtractionGuard(
        max_entries=limits.max_archive_entries,
        max_total_bytes=limits.max_archive_uncompressed_bytes,
    )
