class ArchiveLimitExceeded(ValueError):  # noqa: N818
    """Raised when an archive expands past what one extraction is allowed to buffer."""


class ArchiveExtractionGuard:
    """Bounds one archive extraction in entry count and decompressed byte total."""

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


class GuardedMemberReader:
    """File-like reader that counts each byte against the guard, so a zip bomb stops mid-read."""

    def __init__(self, member_file, guard: ArchiveExtractionGuard, name: str):
        self._f = member_file
        self._guard = guard
        self._name = name

    def read(self, size: int = -1) -> bytes:
        chunk = self._f.read(size)
        if chunk:
            self._guard.account_bytes(len(chunk), self._name)
        return chunk
