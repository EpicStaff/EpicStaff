"""Open untrusted archives without letting their headers decide how much memory is used.
tarfile buffers an extended header's declared size; zipfile builds an object per entry."""

import struct
import tarfile
import zipfile

# One pax/GNU long-name header holds a path (PATH_MAX 4096) and a few attributes.
MAX_TAR_EXTENDED_HEADER_BYTES = 64 * 1024
# Extended headers stacked before one member; real archives use at most three.
MAX_TAR_HEADER_CHAIN = 8
# Global pax headers merge into one archive-wide dict, so their sum is bounded too.
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
    """TarInfo that bounds each header before tarfile processes it.
    Hooks _proc_member and private _proc_gnusparse_10; test_archive_readers guards both."""

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
        """Return `member`, rejecting a negative size or a backwards offset (a re-read loop)."""
        if member.size < 0 or tar.offset <= self.offset:
            raise UnsafeTarHeader(
                f"Archive has a tar header that points backwards: {member.name!r}"
            )
        return member

    def _proc_gnusparse_10(self, next_member, pax_headers, tar):
        # GNU sparse 1.0 reads its map from the data blocks, as many as it declares.
        raise UnsafeTarHeader(f"Archive contains a sparse file: {next_member.name!r}")


class BoundedTarFile(tarfile.TarFile):
    """Read-only TarFile for untrusted archives: bounded headers, members not retained.
    Only iterate it: getmembers(), extractall() and link targets need the dropped list."""

    tarinfo = _BoundedTarInfo
    # Per-archive state for _BoundedTarInfo.
    header_chain = 0
    global_header_bytes = 0

    def __iter__(self):
        # tarfile appends every header to self.members; clearing keeps memory bounded.
        while (member := self.next()) is not None:
            self.members.clear()
            yield member


def open_tar(file_object, mode: str = "r:*") -> BoundedTarFile:
    """Open an untrusted tar for reading with bounded headers."""
    return BoundedTarFile.open(fileobj=file_object, mode=mode)


def is_tar(file_object) -> bool:
    """Whether the bytes open as a tar; UnsafeTarHeader propagates, as a hostile tar is a tar."""
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
    """Count the entries ZipFile would build, from the raw central directory, up to stop_after.
    Walks the directory bytes like ZipFile does, since ZipFile ignores the declared total."""
    position = file_object.tell()
    try:
        # zipfile's private reader, so this finds the same end record ZipFile uses.
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
    """Where ZipFile starts reading the central directory: right before the end records."""
    location = end_record[zipfile._ECD_LOCATION]
    start = location - end_record[zipfile._ECD_SIZE]
    if end_record[zipfile._ECD_SIGNATURE] == zipfile.stringEndArchive64:
        file_object.seek(location)
        if file_object.read(4) == _ZIP_END_SIGNATURE:
            start -= _ZIP64_END_STRUCTURES_SIZE
    return start


def _count_central_headers(file_object, start: int, directory_size: int, stop_after: int) -> int:
    """Count central-directory headers up to stop_after + 1, reading only the fixed part."""
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
