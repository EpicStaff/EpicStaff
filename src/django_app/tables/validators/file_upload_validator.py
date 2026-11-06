import bz2
import gzip
import io
import lzma
import os
import tarfile
import zipfile
import zlib
from dataclasses import dataclass

from rest_framework import serializers

from tables.constants.upload_limits import UploadLimits, default_upload_limits


class _ArchiveTooLarge(ValueError):  # noqa: N818
    """Internal signal that a bounded decompression hit its cap."""


class _ArchiveUnreadable(ValueError):  # noqa: N818
    """Internal signal that a recognised archive cannot be read to the end."""

    def __init__(self):
        super().__init__("is corrupt or unreadable")


# What zipfile/tarfile raise on crafted headers: besides their own errors, a bare
# ValueError (e.g. a bad GNU sparse map), UnicodeDecodeError on a mislabelled
# name, NotImplementedError on an unknown zip version.
_ARCHIVE_READ_ERRORS = (
    tarfile.TarError,
    zipfile.BadZipFile,
    ValueError,
    NotImplementedError,
    OSError,
    EOFError,
)


@dataclass(frozen=True)
class _ArchiveListing:
    """Regular files an archive's headers declare; nothing is extracted."""

    uncompressed_bytes: int
    file_names: list[str]


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

    def _name_problem(self, filename: str, size: int | None) -> str | None:
        """Why this name/size may not be uploaded, or None when it may."""
        if self.is_unsupported_archive(filename):
            ext = os.path.splitext(filename)[1].lower()
            return f"'{ext}' archives are not supported. Use ZIP or TAR instead."
        if self.is_executable_filename(filename):
            return f"'{filename}' has a blocked executable extension"
        if size is not None and size > self._limits.max_file_bytes:
            return (
                f"'{filename}' is too large: {size} bytes, over the limit of "
                f"{self._limits.max_file_bytes} bytes"
            )
        return None

    def validate_name(self, filename: str) -> None:
        """400 if the name may not be uploaded (blocked or unsupported extension)."""
        if problem := self._name_problem(filename, None):
            raise serializers.ValidationError(problem)

    def _bounded_decompress(self, raw: bytes) -> bytes:
        """Inflate an outer gzip/bzip2/xz layer, reading at most one byte past the cap."""
        cap = self._limits.max_archive_uncompressed_bytes
        compressed = io.BytesIO(raw)

        if raw.startswith(b"\x1f\x8b"):
            stream = gzip.GzipFile(fileobj=compressed)
        elif self._is_bzip2(raw):
            stream = bz2.BZ2File(compressed)
        elif raw.startswith(b"\xfd7zXZ\x00"):
            stream = lzma.LZMAFile(compressed)  # noqa: SIM115
        else:
            return raw

        try:
            with stream:
                plain = stream.read(cap + 1)
        except (OSError, EOFError, lzma.LZMAError, zlib.error) as error:
            # Fail closed: a stream that cannot be inflated cannot be checked either.
            raise _ArchiveUnreadable() from error

        if len(plain) > cap:
            raise _ArchiveTooLarge(f"expands to more than {cap} bytes")

        return plain

    @staticmethod
    def _is_bzip2(raw: bytes) -> bool:
        """A bzip2 stream, not just text that happens to start with "BZh".

        The header is "BZh", a block-size digit, then the magic of the first block
        or of the end of an empty stream.
        """
        return (
            raw[:3] == b"BZh"
            and b"1" <= raw[3:4] <= b"9"
            and raw[4:10] in {b"1AY&SY", b"\x17rE8P\x90"}
        )

    def _list_archive(self, raw: bytes) -> _ArchiveListing | None:
        """List a ZIP/TAR archive from its headers alone, or None when it is neither.

        A TAR listing stops one file past ``max_archive_entries``: the archive is
        rejected at that point, so reading further only costs memory and time.
        """
        buf = io.BytesIO(raw)
        if zipfile.is_zipfile(buf):
            buf.seek(0)
            try:
                with zipfile.ZipFile(buf, "r") as zf:
                    entries = [e for e in zf.infolist() if not e.is_dir()]
            except _ARCHIVE_READ_ERRORS as error:
                raise _ArchiveUnreadable() from error
            return _ArchiveListing(
                uncompressed_bytes=sum(e.file_size for e in entries),
                file_names=[e.filename for e in entries],
            )

        plain_buf = io.BytesIO(self._bounded_decompress(raw))
        try:
            # "r:" rather than is_tarfile(): its "r:*" would inflate an inner
            # compressed layer with no cap.
            tf = tarfile.open(fileobj=plain_buf, mode="r:")  # noqa: SIM115
        except tarfile.ReadError:
            return None
        except _ARCHIVE_READ_ERRORS as error:
            raise _ArchiveUnreadable() from error

        members: list[tarfile.TarInfo] = []
        try:
            with tf:
                for member in tf:
                    if not member.isfile():
                        continue
                    members.append(member)
                    if len(members) > self._limits.max_archive_entries:
                        break
        except _ARCHIVE_READ_ERRORS as error:
            # Fail closed: a partial listing would let the unread members skip the checks.
            raise _ArchiveUnreadable() from error
        return _ArchiveListing(
            uncompressed_bytes=sum(m.size for m in members),
            file_names=[m.name for m in members],
        )

    def validate(self, files: list) -> list:
        """
        Validate a list of uploaded files.  Raises
        ``serializers.ValidationError`` if the batch or any single file is over
        its size cap, if any file uses an unsupported archive format, contains
        blocked executable extensions, declares an unsafe expansion, or is an
        archive that cannot be read to the end.
        ZIP and TAR archives are allowed — they are auto-extracted by the
        storage layer and never stored as-is.
        """
        detail_lines: list[str] = []
        total_bytes = 0

        for f in files:
            total_bytes += f.size
            # Block unsupported archives, executables and oversized files before reading
            problem = self._name_problem(f.name, f.size)
            if problem:
                detail_lines.append(problem)
                continue

            position = f.tell()
            raw = f.read()
            f.seek(position)

            try:
                listing = self._list_archive(raw)
            except (_ArchiveTooLarge, _ArchiveUnreadable) as error:
                detail_lines.append(f"Archive '{f.name}' {error}")
                continue

            if listing is None:
                continue

            if len(listing.file_names) > self._limits.max_archive_entries:
                detail_lines.append(
                    f"Archive '{f.name}' contains more than "
                    f"{self._limits.max_archive_entries} entries"
                )
                continue

            if listing.uncompressed_bytes > self._limits.max_archive_uncompressed_bytes:
                detail_lines.append(
                    f"Archive '{f.name}' expands to {listing.uncompressed_bytes} bytes, "
                    f"over the limit of {self._limits.max_archive_uncompressed_bytes} bytes"
                )
                continue

            blocked = [name for name in listing.file_names if self.is_executable_filename(name)]
            if blocked:
                detail_lines.append(
                    f"Archive '{f.name}' contains executable files: " + ", ".join(blocked)
                )

        if total_bytes > self._limits.max_total_bytes:
            detail_lines.append(
                f"Total upload size is {total_bytes} bytes, over the limit of "
                f"{self._limits.max_total_bytes} bytes"
            )

        if detail_lines:
            raise serializers.ValidationError("Upload rejected. " + "; ".join(detail_lines))

        return files
