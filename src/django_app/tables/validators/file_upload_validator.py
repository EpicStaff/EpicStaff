import io
import os
import tarfile
import zipfile

from rest_framework import serializers


class FileValidator:
    """
    Validates uploaded files against a blocklist of executable extensions.
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

    def validate(self, files: list) -> list:
        """
        Validate a list of uploaded files.  Raises
        ``serializers.ValidationError`` if any file uses an unsupported
        archive format or contains blocked executable extensions.
        ZIP and TAR archives are allowed — they are auto-extracted by the
        storage layer and never stored as-is.
        """
        detail_lines: list[str] = []

        for f in files:
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

            # Scan ZIP/TAR contents for executables
            archive_blocked = self.scan_archive_for_executables(f)
            if archive_blocked:
                detail_lines.append(
                    f"Archive '{f.name}' contains executable files: "
                    + ", ".join(archive_blocked)
                )

        if detail_lines:
            raise serializers.ValidationError(
                "Upload rejected. " + "; ".join(detail_lines)
            )

        return files
