"""An uploaded archive is listed once, within the caps, before any verdict on it.

Listing stops as soon as the entry cap is exceeded or the decompressed size
passes its cap, so a small hostile archive cannot make the validator inflate it
in full or hold every header in memory. The size and entry verdicts come before
the executable verdict, because the executable check only sees what the bounded
listing read. An archive that is recognised but cannot be read to the end is
rejected: a partial listing would let the unread members skip every check.
"""

import bz2
import gzip
import io
import lzma
import tarfile
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from tables.constants.upload_limits import UploadLimits
from tables.validators.file_upload_validator import FileValidator


def _validator(**overrides) -> FileValidator:
    limits = {
        "max_file_bytes": 10_000_000,
        "max_total_bytes": 10_000_000,
        "max_archive_entries": 1_000,
        "max_archive_uncompressed_bytes": 1_000_000,
    }
    limits.update(overrides)
    return FileValidator(limits=UploadLimits(**limits))


def _tar_members(files=(), directories=()) -> bytes:
    """Tar headers and data for the given members, without the end-of-archive marker."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for directory in directories:
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, payload in files:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        members_end = archive.offset
    return buffer.getvalue()[:members_end]


def _tar(files=(), directories=()) -> bytes:
    """A complete tar: the members followed by the end-of-archive marker."""
    return _tar_members(files, directories) + b"\0" * (2 * tarfile.BLOCKSIZE)


def _truncated_long_name_header(name: str) -> bytes:
    """A GNU long-name record whose following member header is missing.

    tarfile cannot read past it: listing an archive that ends this way raises.
    """
    record = tarfile.TarInfo(name).tobuf(tarfile.GNU_FORMAT, "utf-8", "surrogateescape")
    return record[: -tarfile.BLOCKSIZE]


def _upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content)


def _assert_tarfile_cannot_list(content: bytes) -> None:
    with (
        pytest.raises(tarfile.ReadError),
        tarfile.open(fileobj=io.BytesIO(content), mode="r:") as archive,
    ):
        archive.getmembers()


def test_listing_stops_once_the_entry_cap_is_exceeded():
    """Members past the cap are never read: a broken header after them is not reached."""
    entry_cap = 3
    content = _tar_members(
        files=[(f"f{index}.txt", b"x") for index in range(entry_cap + 1)]
    ) + _truncated_long_name_header("later/" + "x" * 150 + ".txt")
    _assert_tarfile_cannot_list(content)

    with pytest.raises(ValidationError, match="contains more than 3 entries"):
        _validator(max_archive_entries=entry_cap).validate([_upload("many.tar", content)])


@pytest.mark.parametrize(
    ("file_count", "directory_count", "rejected"),
    [
        (3, 0, False),
        (4, 0, True),
        (3, 2, False),
    ],
    ids=["at-cap", "one-over-cap", "directories-do-not-count"],
)
def test_entry_cap_counts_regular_files_only(file_count, directory_count, rejected):
    content = _tar(
        files=[(f"f{index}.txt", b"x") for index in range(file_count)],
        directories=[f"dir{index}" for index in range(directory_count)],
    )
    upload = _upload("bundle.tar", content)
    validator = _validator(max_archive_entries=3)

    if rejected:
        with pytest.raises(ValidationError, match="entries"):
            validator.validate([upload])
    else:
        assert validator.validate([upload]) == [upload]


def test_tar_with_an_unreadable_later_header_is_rejected():
    """The hidden member is a script; reading only the first header would wave it through."""
    content = _tar_members(files=[("readme.txt", b"hello")]) + _truncated_long_name_header(
        "scripts/" + "x" * 150 + ".sh"
    )
    _assert_tarfile_cannot_list(content)

    with pytest.raises(ValidationError, match="corrupt or unreadable"):
        _validator().validate([_upload("bundle.tar", content)])


@pytest.mark.parametrize(
    "content",
    [
        b"\x1f\x8b" + b"not a gzip stream" * 8,
        # A valid gzip header followed by a broken deflate stream.
        gzip.compress(b"hello world" * 100)[:10] + b"\xff" * 20,
        b"BZh91AY&SY" + b"not a bzip2 stream" * 8,
        b"\xfd7zXZ\x00" + b"not an xz stream" * 8,
    ],
    ids=["gzip", "gzip-deflate", "bzip2", "xz"],
)
def test_corrupt_compressed_layer_is_rejected(content):
    with pytest.raises(ValidationError, match="corrupt or unreadable"):
        _validator().validate([_upload("bundle.tar.gz", content)])


@pytest.mark.parametrize(
    "compress",
    [gzip.compress, bz2.compress, lzma.compress],
    ids=["gzip", "bzip2", "xz"],
)
def test_valid_compressed_tar_with_a_script_is_rejected_for_the_script(compress):
    content = compress(_tar(files=[("readme.txt", b"hello"), ("run.sh", b"#!/bin/sh")]))

    with pytest.raises(ValidationError, match=r"contains executable files: run\.sh"):
        _validator().validate([_upload("bundle.tar.gz", content)])


def test_size_cap_is_reported_before_executables():
    """Past the cap the listing is cut short, so its file names are not a complete answer."""
    content = gzip.compress(_tar(files=[("run.sh", b"\0" * 500_000)]))

    with pytest.raises(ValidationError) as error:
        _validator(max_archive_uncompressed_bytes=1_000).validate(
            [_upload("bundle.tar.gz", content)]
        )

    message = str(error.value)
    assert "expands to more than 1000 bytes" in message
    assert "executable" not in message


def test_archive_is_recognised_by_content_not_by_name():
    content = _tar(files=[("run.sh", b"#!/bin/sh")])

    with pytest.raises(ValidationError, match=r"contains executable files: run\.sh"):
        _validator().validate([_upload("report.pdf", content)])


def test_text_that_starts_like_a_bzip2_header_is_not_an_archive():
    upload = _upload("notes.txt", b"BZh is how this plain-text document happens to begin.\n")

    assert _validator().validate([upload]) == [upload]


def test_zip_with_a_broken_central_directory_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"hello")
    content = buffer.getvalue().replace(b"PK\x01\x02", b"PK\x00\x00")
    assert zipfile.is_zipfile(io.BytesIO(content))

    with pytest.raises(ValidationError, match="corrupt or unreadable"):
        _validator().validate([_upload("bundle.zip", content)])


def test_an_inner_compressed_layer_is_never_inflated(monkeypatch):
    """Only the outer layer is inflated, through the cap; a layer inside it is opaque data."""
    pax_header = tarfile.TarInfo("././@PaxHeader")
    pax_header.type = tarfile.XHDTYPE
    pax_header.size = 5_000_000
    inner = bz2.compress(pax_header.tobuf(tarfile.USTAR_FORMAT) + b"\0" * pax_header.size)
    inflated: list[int] = []
    read = bz2.BZ2File.read

    def counting_read(self, size=-1):
        data = read(self, size)
        inflated.append(len(data))
        return data

    monkeypatch.setattr(bz2.BZ2File, "read", counting_read)

    _validator().validate([_upload("bundle.tar.gz", gzip.compress(inner))])

    assert sum(inflated) <= 1_000_000


def _tar_with_bad_sparse_map(after_another_member: bool) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        if after_another_member:
            archive.addfile(tarfile.TarInfo("readme.txt"))
        info = tarfile.TarInfo("data.bin")
        info.pax_headers = {"GNU.sparse.map": "x,y"}
        archive.addfile(info)
    return buffer.getvalue()


@pytest.mark.parametrize("after_another_member", [False, True], ids=["first", "later"])
def test_tar_with_a_malformed_sparse_map_is_rejected(after_another_member):
    content = _tar_with_bad_sparse_map(after_another_member)

    with pytest.raises(ValidationError, match="corrupt or unreadable"):
        _validator().validate([_upload("bundle.tar", content)])


def _zip_with_central_header(patch) -> bytes:
    """A one-entry zip whose central directory header is rewritten by ``patch``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("caf\u00e9.txt", b"hello")
    content = bytearray(buffer.getvalue())
    patch(content, content.index(b"PK\x01\x02"))
    return bytes(content)


def _unsupported_version(content: bytearray, header: int) -> None:
    content[header + 6 : header + 8] = (213).to_bytes(2, "little")


def _utf8_flag_on_a_latin1_name(content: bytearray, header: int) -> None:
    flags = int.from_bytes(content[header + 8 : header + 10], "little") | 0x800
    content[header + 8 : header + 10] = flags.to_bytes(2, "little")
    name = content.index("caf\u00e9".encode("utf-8"), header)
    content[name : name + 5] = b"caf\xe4."  # same length, invalid UTF-8


@pytest.mark.parametrize(
    "patch",
    [_unsupported_version, _utf8_flag_on_a_latin1_name],
    ids=["unsupported-version", "invalid-utf8-name"],
)
def test_zip_with_an_unreadable_central_header_is_rejected(patch):
    content = _zip_with_central_header(patch)
    assert zipfile.is_zipfile(io.BytesIO(content))

    with pytest.raises(ValidationError, match="corrupt or unreadable"):
        _validator().validate([_upload("bundle.zip", content)])
