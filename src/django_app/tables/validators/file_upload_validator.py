import os

from rest_framework import serializers

from tables.constants.upload_limits import UploadLimits, default_upload_limits
from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.archive_unpacking.extraction_guard import ArchiveLimitExceeded
from tables.services.storage_service.archive_unpacking.inspection import inspect_archive


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

    def _archive_problem(self, file) -> str | None:
        """Why an archive may not be uploaded, or None when it may, or is no archive at all.

        The same header-only inspection the storage upload runs before unpacking, with
        the expansion cap in place of the free quota.
        """
        cap = self._limits.max_archive_uncompressed_bytes
        try:
            inspect_archive(
                file,
                file.name,
                max_entries=self._limits.max_archive_entries,
                free_bytes=cap,
                is_blocked=self.is_executable_filename,
            )
        except StorageQuotaExceeded:
            return f"Archive '{file.name}' expands to more than {cap} bytes"
        except ArchiveLimitExceeded:
            return (
                f"Archive '{file.name}' contains more than "
                f"{self._limits.max_archive_entries} entries"
            )
        except ValueError as error:
            return str(error)
        return None

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

            if archive_problem := self._archive_problem(f):
                detail_lines.append(archive_problem)

        if total_bytes > self._limits.max_total_bytes:
            detail_lines.append(
                f"Total upload size is {total_bytes} bytes, over the limit of "
                f"{self._limits.max_total_bytes} bytes"
            )

        if detail_lines:
            raise serializers.ValidationError("Upload rejected. " + "; ".join(detail_lines))

        return files
