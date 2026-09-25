"""Open uploaded archives without letting their headers decide how much memory is used.

tarfile reads a GNU long-name/long-link or pax header's whole declared size into
memory, and zipfile builds an object for every central-directory entry, both
before a caller sees a single member to count. The readers here refuse such an
archive while its headers are being read."""

import struct
import tarfile
import zipfile

# A pax or GNU long-name/long-link header holds one member's metadata: a path
# (PATH_MAX is 4096) plus a few attributes. 64 KiB is far past any real one, and
# at most MAX_TAR_HEADER_CHAIN of them are held at once.
MAX_TAR_EXTENDED_HEADER_BYTES = 64 * 1024
# Extended headers stacked in front of one member. Real archives use at most
# three (global pax + pax + GNU long name); tarfile recurses once per header.
MAX_TAR_HEADER_CHAIN = 8
# Global pax headers merge into one dict tarfile keeps for the whole archive, so
# their sum is bounded, not only each one (git archive writes a single ~50 bytes).
MAX_TAR_GLOBAL_HEADER_BYTES = 64 * 1024

_EXTENDED_HEADER_TYPES = frozenset(
    {
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.SOLARIS_XHDTYPE,
    }
)

# Central directory file header: 46 fixed bytes, then name, extra field and comment.
_ZIP_CENTRAL_HEADER_SIZE = 46
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_END_SIGNATURE = b"PK\x05\x06"
# Zip64 end record (56 bytes) + its locator (20 bytes) sit before the classic one.
_ZIP64_END_STRUCTURES_SIZE = 56 + 20


class UnsafeTarHeader(ValueError):  # noqa: N818 (named like ArchiveLimitExceeded)
    """A tar header that would make tarfile buffer or recurse past the bounds above."""


class _BoundedTarInfo(tarfile.TarInfo):
    """TarInfo that checks each header before tarfile processes it.

    _proc_member is the per-header dispatch that tarfile documents as the hook for
    subclasses; it runs for every header, including the one that follows an
    extended header (tarfile reads that through self.fromtarfile, a classmethod,
    so it is a _BoundedTarInfo too). _proc_gnusparse_10 is private: signature
    checked against CPython 3.12.3 and 3.12.10. test_archive_readers fails
    loudly if tarfile stops calling either (the bomb would then be read)."""

    def _proc_member(self, tar):
        if self.size < 0:
            raise UnsafeTarHeader(f"Archive has a tar header with a negative size: {self.name!r}")
        if self.type == tarfile.GNUTYPE_SPARSE:
            # _proc_sparse collects the sparse map from an unbounded run of blocks.
            raise UnsafeTarHeader(f"Archive contains a sparse file: {self.name!r}")
        if self.type not in _EXTENDED_HEADER_TYPES:
            return self._moving_forward(tar, super()._proc_member(tar))

        if self.size > MAX_TAR_EXTENDED_HEADER_BYTES:
            raise UnsafeTarHeader(
                f"Archive has a tar header of {self.size} bytes, over the limit of "
                f"{MAX_TAR_EXTENDED_HEADER_BYTES}"
            )
        if self.type == tarfile.XGLTYPE:
            tar.global_header_bytes += self.size
            if tar.global_header_bytes > MAX_TAR_GLOBAL_HEADER_BYTES:
                raise UnsafeTarHeader(
                    f"Archive's global tar headers exceed {MAX_TAR_GLOBAL_HEADER_BYTES} bytes"
                )
        if tar.header_chain >= MAX_TAR_HEADER_CHAIN:
            raise UnsafeTarHeader(
                f"Archive stacks more than {MAX_TAR_HEADER_CHAIN} tar headers on one member"
            )
        tar.header_chain += 1
        try:
            return self._moving_forward(tar, super()._proc_member(tar))
        finally:
            tar.header_chain -= 1

    def _moving_forward(self, tar, member):
        """`member` unless its size (possibly set by a pax `size` or `GNU.sparse.size`
        record) is negative or the next header would not come after this one: a
        backwards offset makes tarfile re-read earlier members in a loop."""
        if member.size < 0 or tar.offset <= self.offset:
            raise UnsafeTarHeader(
                f"Archive has a tar header that points backwards: {member.name!r}"
            )
        return member

    def _proc_gnusparse_10(self, next_member, pax_headers, tar):
        # GNU sparse 1.0 reads its map from the data blocks, as many as it declares.
        raise UnsafeTarHeader(f"Archive contains a sparse file: {next_member.name!r}")


class BoundedTarFile(tarfile.TarFile):
    """Read-only TarFile for untrusted archives: bounded headers (_BoundedTarInfo)
    and iteration that does not keep every member it has passed.

    Only iterate it: getmembers(), extractall() and link targets need the member
    list that iteration drops."""

    tarinfo = _BoundedTarInfo
    # Per-archive state for _BoundedTarInfo; class defaults, set per instance on use.
    header_chain = 0
    global_header_bytes = 0

    def __iter__(self):
        # tarfile appends every header it reads to self.members; nothing reads them
        # back here, so without this a long archive grows the list to its end.
        while (member := self.next()) is not None:
            self.members.clear()
            yield member


def open_tar(file_object, mode: str = "r:*") -> BoundedTarFile:
    """tarfile.open for reading an untrusted archive. UnsafeTarHeader when a
    header is over the bounds above (a ValueError, not a tarfile.TarError)."""
    return BoundedTarFile.open(fileobj=file_object, mode=mode)


def is_tar(file_object) -> bool:
    """tarfile.is_tarfile over open_tar, since is_tarfile takes no tarinfo: whether
    the bytes open as a tar. Anything tarfile cannot read is simply not a tar,
    but UnsafeTarHeader propagates, since the bytes are a tar, a hostile one.
    Leaves the file position where it was."""
    position = file_object.tell()
    try:
        with open_tar(file_object):
            return True
    except UnsafeTarHeader:
        raise
    except Exception:  # is_tarfile's contract, plus codec errors it lets through
        return False
    finally:
        file_object.seek(position)


def zip_entry_count(file_object, *, stop_after: int) -> int:
    """How many entries zipfile.ZipFile would build from this archive, counted
    from the raw central directory without building them. Past `stop_after` it
    returns as soon as that is known, with a number over stop_after but not
    necessarily the full count. The declared total is not trusted: ZipFile
    ignores it and reads entries until the directory's byte size is used up, so
    this walks the same bytes. Stops quietly at anything malformed and leaves reporting it to
    ZipFile. BadZipFile: no end-of-central-directory record. Leaves the file
    position where it was."""
    position = file_object.tell()
    try:
        # zipfile's own reader (private, stable since Python 2), so the record found
        # here is the one ZipFile will use; it also resolves the zip64 record.
        try:
            end_record = zipfile._EndRecData(file_object)
        except OSError as exc:
            raise zipfile.BadZipFile("File is not a zip file") from exc
        if not end_record:
            raise zipfile.BadZipFile("File is not a zip file")

        declared = end_record[zipfile._ECD_ENTRIES_TOTAL]
        if declared > stop_after:
            return declared

        directory_start = _zip_directory_start(file_object, end_record)
        if directory_start < 0:
            return 0
        return _count_central_headers(
            file_object, directory_start, end_record[zipfile._ECD_SIZE], stop_after
        )
    finally:
        file_object.seek(position)


def _zip_directory_start(file_object, end_record) -> int:
    """Where ZipFile._RealGetContents starts reading the central directory: right
    before the end records, whatever the directory offset field claims.

    For zip64, CPython versions disagree on what the record location points at
    (the classic end record in 3.12.10, the zip64 one in later patch releases);
    reading the signature there covers both."""
    location = end_record[zipfile._ECD_LOCATION]
    start = location - end_record[zipfile._ECD_SIZE]
    if end_record[zipfile._ECD_SIGNATURE] == zipfile.stringEndArchive64:
        file_object.seek(location)
        if file_object.read(4) == _ZIP_END_SIGNATURE:
            start -= _ZIP64_END_STRUCTURES_SIZE
    return start


def _count_central_headers(file_object, start: int, directory_size: int, stop_after: int) -> int:
    """Entries in the directory as ZipFile parses them, up to stop_after + 1. Reads
    only each fixed header, so the cost is bounded by stop_after, not the directory."""
    count = offset = 0
    while offset < directory_size and count <= stop_after:
        file_object.seek(start + offset)
        header = file_object.read(_ZIP_CENTRAL_HEADER_SIZE)
        if len(header) < _ZIP_CENTRAL_HEADER_SIZE or header[:4] != _ZIP_CENTRAL_SIGNATURE:
            break
        name_length, extra_length, comment_length = struct.unpack_from("<3H", header, 28)
        count += 1
        offset += _ZIP_CENTRAL_HEADER_SIZE + name_length + extra_length + comment_length
    return count
