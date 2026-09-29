import zipfile
from collections.abc import Iterator

from tables.services.storage_service.archive.extraction_guard import (
    ArchiveExtractionGuard,
    GuardedMemberReader,
)
from tables.services.storage_service.archive.safe_readers import is_tar, open_tar
from tables.services.storage_service.path_utils import sanitize_storage_path


def iter_archive_members(
    archive_file, guard: ArchiveExtractionGuard
) -> Iterator[tuple[str, GuardedMemberReader]]:
    """Yield (safe_name, GuardedMemberReader) per file member, streaming.

    Rejects symlinks, hardlinks and any tar member that is not a plain file or
    folder (every tar member, folders too, counts toward the guard's entry
    cap) and sanitizes names, but does not read member bytes here — the
    caller streams each reader to storage before advancing to the next
    member (member stays open during the yield)."""
    pos = archive_file.tell()

    if zipfile.is_zipfile(archive_file):
        archive_file.seek(pos)

        with zipfile.ZipFile(archive_file, "r") as zf:
            for entry in zf.infolist():
                if entry.is_dir():
                    continue
                guard.account_entry()
                safe_name = _sanitize_archive_member_name(entry.filename)
                with zf.open(entry, "r") as member_file:
                    yield safe_name, GuardedMemberReader(member_file, guard, entry.filename)
        return

    archive_file.seek(pos)

    if is_tar(archive_file):
        with open_tar(archive_file) as tf:
            # Lazily, not getmembers(): that inflates the whole archive first.
            for member in tf:
                guard.account_entry()
                if member.issym() or member.islnk():
                    raise ValueError(f"Archive member is a symlink or hardlink: {member.name!r}")
                if member.isdir():
                    continue
                if not member.isfile() or member.issparse():
                    raise ValueError(
                        f"Archive member is not a plain file or folder: {member.name!r}"
                    )
                safe_name = _sanitize_archive_member_name(member.name)
                fobj = tf.extractfile(member)
                if fobj:
                    yield safe_name, GuardedMemberReader(fobj, guard, member.name)
        return

    archive_file.seek(pos)
    raise ValueError("Unsupported archive format — expected ZIP or TAR")


def _sanitize_archive_member_name(name: str) -> str:
    """Raise ValueError if an archive member name can escape the extraction folder."""
    return sanitize_storage_path(name, allow_empty=False)
