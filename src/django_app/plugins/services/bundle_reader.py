import io
import zipfile
import zlib
from dataclasses import dataclass

from rest_framework import serializers
from tables.services.storage_service.archive_unpacking.extraction import iter_archive_members
from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
)
from tables.services.storage_service.archive_unpacking.safe_readers import zip_entry_count
from tables.validators.file_upload_validator import FileValidator

from plugins.exceptions import InvalidPluginError

MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 200
MAX_BUNDLE_UNPACKED_BYTES = 50 * 1024 * 1024

# Junk an OS adds when zipping a folder; dropped instead of rejected.
_IGNORED_SEGMENTS = frozenset({"__MACOSX", ".DS_Store"})


@dataclass(frozen=True)
class PluginBundle:
    """The files of an uploaded plugin zip, keyed by their sanitised path."""

    files: dict[str, bytes]

    def has(self, path: str) -> bool:
        return path in self.files

    def read(self, path: str) -> bytes:
        return self.files[path]

    def paths_under(self, folder: str) -> list[str]:
        prefix = folder.rstrip("/") + "/"
        return sorted(path for path in self.files if path.startswith(prefix))


def read_bundle(uploaded_file) -> PluginBundle:
    """Unpack an uploaded plugin zip in memory, enforcing the size and entry caps.

    Raises:
        InvalidPluginError: not a zip, over a cap, an unsafe member name, a blocked
            file type, or a damaged archive.
    """
    if uploaded_file.size > MAX_BUNDLE_BYTES:
        raise _invalid(f"The file is larger than {MAX_BUNDLE_BYTES // (1024 * 1024)} MB.")

    uploaded_file.seek(0)
    buffer = io.BytesIO(uploaded_file.read(MAX_BUNDLE_BYTES + 1))
    if len(buffer.getbuffer()) > MAX_BUNDLE_BYTES:
        raise _invalid(f"The file is larger than {MAX_BUNDLE_BYTES // (1024 * 1024)} MB.")
    if not zipfile.is_zipfile(buffer):
        raise _invalid("A plugin must be a .zip file.")
    buffer.seek(0)

    validator = FileValidator()
    guard = ArchiveExtractionGuard(
        max_entries=MAX_BUNDLE_ENTRIES, max_total_bytes=MAX_BUNDLE_UNPACKED_BYTES
    )
    files: dict[str, bytes] = {}
    try:
        if zip_entry_count(buffer, stop_after=MAX_BUNDLE_ENTRIES) > MAX_BUNDLE_ENTRIES:
            raise _invalid(f"The zip holds more than {MAX_BUNDLE_ENTRIES} entries.")
        for name, reader in iter_archive_members(buffer, guard):
            if _IGNORED_SEGMENTS & set(name.split("/")):
                continue
            validator.validate_name(name)
            if name in files:
                raise _invalid(f"The zip holds '{name}' twice.")
            files[name] = reader.read()
    except serializers.ValidationError as exc:
        raise _invalid(_validation_message(exc)) from exc
    # zipfile reports a damaged, encrypted or oddly compressed member through these.
    except (
        ValueError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ) as exc:
        raise _invalid(f"The zip could not be read: {exc}") from exc

    return PluginBundle(files=_strip_wrapping_folder(files))


def _strip_wrapping_folder(files: dict[str, bytes]) -> dict[str, bytes]:
    """Accept a zip of the plugin folder itself, not only of its contents.

    Zipping a folder puts every file under "<folder>/". When plugin.json is not at
    the root but every entry shares one top folder that holds it, drop that folder.
    """
    if "plugin.json" in files or not files:
        return files
    top_folders = {path.split("/", 1)[0] for path in files}
    if len(top_folders) != 1 or any("/" not in path for path in files):
        return files
    prefix = f"{top_folders.pop()}/"
    if f"{prefix}plugin.json" not in files:
        return files
    return {path.removeprefix(prefix): content for path, content in files.items()}


def _validation_message(exc: serializers.ValidationError) -> str:
    detail = exc.detail
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    return str(detail)


def _invalid(message: str) -> InvalidPluginError:
    return InvalidPluginError([{"loc": "bundle", "message": message}])
