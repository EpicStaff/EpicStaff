import lzma
import tarfile
import zipfile
import zlib

from src.shared.epicstaff_storage.path_safety import sanitize_storage_path
from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.archive_unpacking.extraction_guard import ArchiveLimitExceeded
from tables.services.storage_service.archive_unpacking.safe_readers import (
    UnsafeTarHeader,
    is_tar,
    open_tar,
    zip_entry_count,
)
from tables.services.storage_service.path_utils import check_new_name

# Bytes with one of these signatures that fail to parse are a broken archive, not a plain file.
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"\x1f\x8b", b"\xfd7zXZ\x00")
# bzip2 is "BZh", a block-size digit, then the magic of the first block or of the end of an
# empty stream: "BZh" alone also starts plain text.
_BZIP2_BLOCK_MAGICS = (b"1AY&SY", b"\x17rE8P\x90")
_TAR_MAGIC_OFFSET = 257

# Other methods (Deflate64, implode) pass the directory check and fail only on extraction.
_SUPPORTED_ZIP_COMPRESSION = frozenset(
    {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
)


def inspect_archive(
    file_object, filename: str, *, max_entries: int, free_bytes: int, is_blocked
) -> list[str] | None:
    """Validate a buffered archive before extraction.
    Returns its folder entries, or None when the bytes are not an archive."""
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
            if is_blocked(safe_name):
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
    return (
        head.startswith(_ARCHIVE_SIGNATURES)
        or _is_bzip2(head)
        or head[_TAR_MAGIC_OFFSET:] == b"ustar"
    )


def _is_bzip2(head: bytes) -> bool:
    return head[:3] == b"BZh" and b"1" <= head[3:4] <= b"9" and head[4:10] in _BZIP2_BLOCK_MAGICS


def _zip_members(file_object, filename: str, max_entries: int):
    """Yield (name, declared size, is_dir) per zip member from the central directory.
    Entries are counted before ZipFile builds an object for each one."""
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
    except (zipfile.BadZipFile, NotImplementedError, UnicodeDecodeError) as exc:
        # A wrecked central directory can raise NotImplementedError instead of BadZipFile,
        # and a name flagged UTF-8 that is not raises UnicodeDecodeError.
        raise ValueError(f"Archive '{filename}' is damaged or unreadable") from exc


def _tar_members(file_object, filename: str):
    """Yield (name, size, is_dir) per tar member, reading headers lazily."""
    for member in _tar_headers(file_object, filename):
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


def _tar_headers(file_object, filename: str):
    """Yield each tar member; any failure to read the headers is a damaged archive."""
    try:
        with open_tar(file_object) as tf:
            yield from tf
    except UnsafeTarHeader:
        raise
    # tarfile raises a bare ValueError on a malformed pax value, such as a GNU sparse map.
    except (tarfile.TarError, OSError, EOFError, zlib.error, lzma.LZMAError, ValueError) as exc:
        raise ValueError(f"Archive '{filename}' is damaged or unreadable") from exc
