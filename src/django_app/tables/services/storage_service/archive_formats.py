import lzma
import tarfile
import zipfile
import zlib

from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.archive_limits import ArchiveLimitExceeded
from tables.services.storage_service.archive_readers import (
    is_tar,
    open_tar,
    zip_entry_count,
)
from tables.services.storage_service.path_utils import check_new_name, sanitize_storage_path

DOCUMENT_EXTENSIONS = frozenset(
    {
        # Microsoft Office (OOXML)
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".docx",
        ".docm",
        ".dotx",
        ".pptx",
        ".pptm",
        ".ppsx",
        ".potx",
        # OpenDocument
        ".ods",
        ".odt",
        ".odp",
        ".odg",
        ".odf",
        ".ots",
        ".ott",
        ".otp",
        # Other ZIP-based formats that should not be extracted
        ".epub",
        ".apk",
        ".jar",
        ".war",
        ".xpi",
    }
)


ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".taz",
    ".tar.gz",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
    ".tar.xz",
    ".txz",
)


def is_archive_name(filename: str) -> bool:
    """Whether the name says "archive to unpack" (office/epub/jar files do not)."""
    low = filename.lower()
    if any(low.endswith(doc) for doc in DOCUMENT_EXTENSIONS):
        return False
    return any(low.endswith(sfx) for sfx in ARCHIVE_SUFFIXES)


def strip_archive_suffix(filename: str) -> str:
    """ "bundle.tar.gz" -> "bundle": the name of the folder an archive unpacks into."""
    low = filename.lower()
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if low.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


# Magic bytes of what the archive route can unpack: bytes carrying one of these
# but failing to parse are a broken archive, not a plain file to store as is.
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")
_TAR_MAGIC_OFFSET = 257

# What zipfile can inflate; any other method (Deflate64, implode, ...) passes the
# central directory and only fails with NotImplementedError once extracted.
_SUPPORTED_ZIP_COMPRESSION = frozenset(
    {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
)


def inspect_archive(
    file_object, filename: str, *, max_entries: int, free_bytes: int, is_blocked
) -> list[str] | None:
    """Check a buffered archive before any of it is written. Returns its directory
    entries (sanitized, possibly []), or None when the bytes carry no archive
    signature at all (the name alone can lie). One pass over the headers,
    stopping at the first limit hit, so a bomb costs no more than `free_bytes`
    of decompression. Leaves the file position where it was.

    ValueError: empty, encrypted, damaged, symlinked, too many entries, a member
    that is not a plain file or folder, an unsupported compression method, an
    oversized tar header, a bad or escaping member name, a file clashing with a
    folder, or a blocked extension inside. StorageQuotaExceeded: the declared
    unpacked size does not fit."""
    pos = file_object.tell()
    try:
        if zipfile.is_zipfile(file_object):
            file_object.seek(pos)
            members = _zip_members(file_object, filename, max_entries)
        else:
            file_object.seek(pos)
            if not is_tar(file_object):
                if _has_archive_signature(file_object):
                    raise ValueError(f"Archive '{filename}' is damaged or unreadable")
                return None
            members = _tar_members(file_object, filename)

        entries = total = 0
        blocked: list[str] = []
        files: set[str] = set()
        dirs: set[str] = set()
        for name, size, is_dir in members:
            entries += 1
            if entries > max_entries:
                raise ArchiveLimitExceeded(f"Archive contains more than {max_entries} entries")
            safe_name = sanitize_storage_path(name, allow_empty=False)
            check_new_name(safe_name)
            if is_dir:
                dirs.add(safe_name)
                continue
            total += size
            if total > free_bytes:
                raise StorageQuotaExceeded()
            files.add(safe_name)
            if is_blocked(name):
                blocked.append(name)
        if blocked:
            raise ValueError(
                f"Archive '{filename}' contains executable files: " + ", ".join(blocked)
            )
        if not entries:
            raise ValueError(f"Archive '{filename}' is empty")
        folders = dirs | {parent for f in files for parent in _parents(f)}
        if clash := sorted(files & folders):
            raise ValueError(
                f"Archive '{filename}' has a file and a folder with the same name: {clash[0]!r}"
            )
        return sorted(dirs)
    finally:
        file_object.seek(pos)


def _parents(path: str) -> list[str]:
    """ "a/b/c.txt" -> ["a", "a/b"]."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def _has_archive_signature(file_object) -> bool:
    head = file_object.read(_TAR_MAGIC_OFFSET + 5)
    return head.startswith(_ARCHIVE_SIGNATURES) or head[_TAR_MAGIC_OFFSET:] == b"ustar"


def _zip_members(file_object, filename: str, max_entries: int):
    """(name, declared size, is_dir) per member, from the central directory only.
    The entries are counted before ZipFile builds one object for each of them."""
    try:
        if zip_entry_count(file_object, stop_after=max_entries) > max_entries:
            raise ArchiveLimitExceeded(f"Archive contains more than {max_entries} entries")
        with zipfile.ZipFile(file_object, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    yield entry.filename, 0, True
                    continue
                if entry.flag_bits & 0x1:
                    raise ValueError(f"Archive '{filename}' contains password-protected files")
                if entry.compress_type not in _SUPPORTED_ZIP_COMPRESSION:
                    method = zipfile.compressor_names.get(entry.compress_type, entry.compress_type)
                    raise ValueError(
                        f"Archive '{filename}' compresses {entry.filename!r} with an unsupported "
                        f"method ({method}); re-create it with standard Deflate compression"
                    )
                yield entry.filename, entry.file_size, False
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        # A wrecked central directory can read as an unsupported zip version,
        # which zipfile reports as NotImplementedError rather than BadZipFile.
        raise ValueError(f"Archive '{filename}' is damaged or unreadable") from exc


def _tar_members(file_object, filename: str):
    """(name, size, is_dir) per member; headers are read lazily, so an early stop
    skips decompressing the rest. Every member is yielded or rejected, so each
    one counts toward the entry limit."""
    try:
        with open_tar(file_object) as tf:
            for member in tf:
                if member.issym() or member.islnk():
                    raise ValueError(
                        f"Archive '{filename}' contains a symlink or hardlink: {member.name!r}"
                    )
                if member.isdir():
                    yield member.name, 0, True
                elif member.isfile() and not member.issparse():
                    yield member.name, member.size, False
                else:
                    raise ValueError(
                        f"Archive '{filename}' contains {member.name!r}, which is not a "
                        "plain file or folder"
                    )
    except (tarfile.TarError, OSError, EOFError, zlib.error, lzma.LZMAError) as exc:
        raise ValueError(f"Archive '{filename}' is damaged or unreadable") from exc
