import bz2
import gzip
import io
import lzma
import os
import tarfile
import zipfile

from rest_framework import serializers

from tables.constants.upload_limits import UploadLimits, default_upload_limits


class _ArchiveTooLarge(ValueError):
    """Internal signal that a bounded decompression hit its cap."""


class FileValidator:
    """
    Validates uploaded files against a blocklist of executable extensions and
    the size and archive-expansion caps in UploadLimits.
    Inspects archive contents (ZIP/TAR) without extracting file data.
    """

    BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
        {
            # Windows executables & installers
            ".exe",
            ".msi",
            ".com",
            ".scr",
            ".pif",
            # Windows scripting
            ".bat",
            ".cmd",
            ".vbs",
            ".vbe",
            ".wsh",
            ".wsf",
            ".ps1",
            ".psm1",
            ".psd1",
            # Unix/macOS executables
            ".sh",
            ".bash",
            ".csh",
            ".ksh",
            ".zsh",
            ".app",
            ".command",
            ".elf",
            # Java archives (executable)
            ".jar",
            ".war",
            ".ear",
            # Shared libraries
            ".dll",
            ".so",
            ".dylib",
        }
    )

    BLOCKED_ARCHIVE_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".rar",
            ".7z",
            ".cab",
            ".iso",
            ".arj",
            ".lzh",
            ".ace",
            ".arc",
            ".lz",
            ".lzma",
            ".zst",
        }
    )

    def __init__(self, *, limits: UploadLimits | None = None):
        self._limits = limits or default_upload_limits()

    def is_executable_filename(self, filename: str) -> bool:
        return os.path.splitext(filename)[1].lower() in self.BLOCKED_EXTENSIONS

    def is_unsupported_archive(self, filename: str) -> bool:
        return os.path.splitext(filename)[1].lower() in self.BLOCKED_ARCHIVE_EXTENSIONS

    def scan_archive_for_executables(self, file_obj) -> list[str]:
        """
        Inspect a ZIP or TAR archive in memory and return entry paths that
        have blocked extensions.  Only reads the directory listing — no
        content is extracted.  Resets file position after inspection.
        """
        pos = file_obj.tell()
        data = file_obj.read()
        file_obj.seek(pos)

        blocked: list[str] = []
        buf = io.BytesIO(data)

        if zipfile.is_zipfile(buf):
            buf.seek(0)
            with zipfile.ZipFile(buf, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith("/") and self.is_executable_filename(name):
                        blocked.append(name)
            return blocked

        buf.seek(0)
        try:
            is_tar = tarfile.is_tarfile(buf)
        except Exception:
            is_tar = False

        if is_tar:
            buf.seek(0)
            with tarfile.open(fileobj=buf, mode="r:*") as tf:
                for member in tf.getmembers():
                    if member.isfile() and self.is_executable_filename(member.name):
                        blocked.append(member.name)
            return blocked

        return blocked

    def _bounded_decompress(self, raw: bytes) -> bytes | None:
        """Inflate an outer gzip/bzip2/xz layer, reading at most one byte past the cap."""
        cap = self._limits.max_archive_uncompressed_bytes
        compressed = io.BytesIO(raw)

        if raw.startswith(b"\x1f\x8b"):
            stream = gzip.GzipFile(fileobj=compressed)
        elif raw.startswith(b"BZh"):
            stream = bz2.BZ2File(compressed)
        elif raw.startswith(b"\xfd7zXZ\x00"):
            stream = lzma.LZMAFile(compressed)
        else:
            return raw

        try:
            with stream:
                plain = stream.read(cap + 1)
        except (OSError, EOFError, lzma.LZMAError):
            return None

        if len(plain) > cap:
            raise _ArchiveTooLarge(f"expands to more than {cap} bytes")

        return plain

    def _declared_archive_contents(self, raw: bytes) -> tuple[int, int] | None:
        """Return (entry count, declared uncompressed bytes), reading headers only."""
        buf = io.BytesIO(raw)
        if zipfile.is_zipfile(buf):
            buf.seek(0)
            with zipfile.ZipFile(buf, "r") as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                return len(entries), sum(e.file_size for e in entries)

        plain = self._bounded_decompress(raw)
        if plain is None:
            return None

        plain_buf = io.BytesIO(plain)
        try:
            if not tarfile.is_tarfile(plain_buf):
                return None
            plain_buf.seek(0)
            with tarfile.open(fileobj=plain_buf, mode="r:") as tf:
                members = [m for m in tf.getmembers() if m.isfile()]
                return len(members), sum(m.size for m in members)
        except (tarfile.TarError, OSError, EOFError):
            return None

    def scan_archive_expansion(self, file_obj) -> str | None:
        """Return why an archive's declared expansion is unsafe, or None when it is fine."""
        pos = file_obj.tell()
        raw = file_obj.read()
        file_obj.seek(pos)

        try:
            declared = self._declared_archive_contents(raw)
        except _ArchiveTooLarge as e:
            return str(e)

        if declared is None:
            return None

        entries, uncompressed = declared

        if entries > self._limits.max_archive_entries:
            return (
                f"contains {entries} entries, over the limit of "
                f"{self._limits.max_archive_entries}"
            )

        if uncompressed > self._limits.max_archive_uncompressed_bytes:
            return (
                f"expands to {uncompressed} bytes, over the limit of "
                f"{self._limits.max_archive_uncompressed_bytes} bytes"
            )

        return None

    def validate(self, files: list) -> list:
        """
        Validate a list of uploaded files.  Raises
        ``serializers.ValidationError`` if the batch or any single file is over
        its size cap, if any file uses an unsupported archive format, contains
        blocked executable extensions, or declares an unsafe expansion.
        ZIP and TAR archives are allowed — they are auto-extracted by the
        storage layer and never stored as-is.
        """
        detail_lines: list[str] = []
        total_bytes = 0

        for f in files:
            total_bytes += f.size

            # Block unsupported archive formats first
            if self.is_unsupported_archive(f.name):
                ext = os.path.splitext(f.name)[1].lower()
                detail_lines.append(
                    f"'{ext}' archives are not supported. Use ZIP or TAR instead."
                )
                continue

            # Block executable file extensions
            if self.is_executable_filename(f.name):
                detail_lines.append(f"'{f.name}' has a blocked executable extension")
                continue

            # Reject a file too large to accept before inspecting its contents
            if f.size > self._limits.max_file_bytes:
                detail_lines.append(
                    f"'{f.name}' is too large: {f.size} bytes, over the limit of "
                    f"{self._limits.max_file_bytes} bytes"
                )
                continue

            # Scan ZIP/TAR contents for executables
            archive_blocked = self.scan_archive_for_executables(f)
            if archive_blocked:
                detail_lines.append(
                    f"Archive '{f.name}' contains executable files: "
                    + ", ".join(archive_blocked)
                )
                continue

            # Reject an archive whose headers declare an unsafe expansion
            expansion_problem = self.scan_archive_expansion(f)
            if expansion_problem:
                detail_lines.append(f"Archive '{f.name}' {expansion_problem}")

        if total_bytes > self._limits.max_total_bytes:
            detail_lines.append(
                f"Total upload size is {total_bytes} bytes, over the limit of "
                f"{self._limits.max_total_bytes} bytes"
            )

        if detail_lines:
            raise serializers.ValidationError(
                "Upload rejected. " + "; ".join(detail_lines)
            )

        return files
