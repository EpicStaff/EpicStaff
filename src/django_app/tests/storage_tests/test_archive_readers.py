"""Bounded readers for untrusted archives.

Every "bomb" here declares a size or count just over the bound and carries only
a few KiB of real bytes: rejection is asserted by the bound firing, never by
running out of memory. If CPython stops calling the TarInfo hooks the bounds
live in, the bomb tests fail (the header is then parsed instead of rejected).
"""

import gzip
import io
import struct
import tarfile
import zipfile

import pytest

from tables.services.storage_service.archive_readers import (
    MAX_TAR_EXTENDED_HEADER_BYTES,
    MAX_TAR_GLOBAL_HEADER_BYTES,
    MAX_TAR_HEADER_CHAIN,
    UnsafeTarHeader,
    is_tar,
    open_tar,
    zip_entry_count,
)

BLOCK = tarfile.BLOCKSIZE
END_OF_ARCHIVE = b"\0" * BLOCK * 2


def _padded(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % BLOCK)


def _header(name: str, member_type: bytes, size: int) -> bytes:
    info = tarfile.TarInfo(name)
    info.type = member_type
    info.size = size
    return info.tobuf(format=tarfile.GNU_FORMAT)


def _extended(member_type: bytes, payload: bytes, declared_size: int | None = None) -> bytes:
    """A GNU long-name/long-link or pax header whose size field may lie."""
    size = len(payload) if declared_size is None else declared_size
    return _header("././@LongLink", member_type, size) + _padded(payload)


def _file(name: str, data: bytes = b"x") -> bytes:
    return _header(name, tarfile.REGTYPE, len(data)) + _padded(data)


def _tar(members, *, tar_format=tarfile.GNU_FORMAT, mode="w") -> io.BytesIO:
    """members: (name, bytes) for a file, (name, None) for a folder."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode, format=tar_format) as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def _names(file_object) -> list[str]:
    with open_tar(file_object) as tf:
        return [member.name for member in tf]


class TestExtendedHeaderBound:
    def test_a_gnu_long_name_over_the_bound_is_rejected_in_a_tar_gz(self):
        # 1 MiB of name compresses to about 1 KiB: the upload is tiny, the header is not
        long_name = "a" * (1024 * 1024)
        archive = _tar([(long_name, b"x")], mode="w:gz")
        assert len(archive.getvalue()) < 16 * 1024

        with pytest.raises(UnsafeTarHeader, match="tar header of"):
            _names(archive)

    def test_a_declared_size_is_rejected_before_it_is_read(self):
        # 512 MiB declared, 10 bytes present: the bound fires on the size field alone
        declared = 512 * 1024 * 1024
        raw = _extended(tarfile.GNUTYPE_LONGNAME, b"a" * 10, declared) + _file("x") + END_OF_ARCHIVE

        with pytest.raises(UnsafeTarHeader, match=str(declared)):
            _names(io.BytesIO(gzip.compress(raw)))

    def test_a_gnu_long_link_over_the_bound_is_rejected(self):
        raw = (
            _extended(tarfile.GNUTYPE_LONGLINK, b"t" * 10, MAX_TAR_EXTENDED_HEADER_BYTES + 1)
            + _file("x")
            + END_OF_ARCHIVE
        )
        with pytest.raises(UnsafeTarHeader):
            _names(io.BytesIO(raw))

    def test_a_pax_header_over_the_bound_is_rejected(self):
        long_name = "p" * (1024 * 1024)
        archive = _tar([(long_name, b"x")], tar_format=tarfile.PAX_FORMAT, mode="w:gz")

        with pytest.raises(UnsafeTarHeader, match="tar header of"):
            _names(archive)

    def test_a_header_just_under_the_bound_is_read(self):
        name = "n" * (MAX_TAR_EXTENDED_HEADER_BYTES - 1)  # plus NUL = the bound exactly
        assert _names(_tar([(name, b"x")])) == [name]

    @pytest.mark.parametrize("tar_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_ordinary_long_and_nested_names_still_work(self, tar_format):
        deep = "/".join(["folder-with-a-long-name"] * 12) + "/file.txt"
        unicode_name = "папка/файл-" + "ü" * 150 + ".txt"
        members = [("empty", None), (deep, b"deep"), (unicode_name, b"u"), ("top.txt", b"t")]

        assert _names(_tar(members, tar_format=tar_format, mode="w:gz")) == [
            "empty",
            deep,
            unicode_name,
            "top.txt",
        ]


class TestGlobalHeadersAndChains:
    def test_one_small_global_header_like_git_archive_is_fine(self):
        buf = io.BytesIO()
        with tarfile.open(
            fileobj=buf, mode="w", format=tarfile.PAX_FORMAT, pax_headers={"comment": "a" * 40}
        ) as tf:
            info = tarfile.TarInfo("a.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
        buf.seek(0)
        assert _names(buf) == ["a.txt"]

    def test_global_headers_are_bounded_in_total_not_only_each(self):
        each = MAX_TAR_GLOBAL_HEADER_BYTES // 2
        raw = b"".join(
            tarfile.TarInfo.create_pax_global_header({f"key{i}": "v" * (each - 20)})
            for i in range(3)
        )
        raw += _file("a.txt") + END_OF_ARCHIVE

        with pytest.raises(UnsafeTarHeader, match="global tar headers"):
            _names(io.BytesIO(raw))

    def test_a_long_chain_of_extended_headers_is_rejected_before_recursing(self):
        # without the cap each header is one more level of recursion in tarfile
        chain = _extended(tarfile.GNUTYPE_LONGNAME, b"name\0") * (MAX_TAR_HEADER_CHAIN + 1)
        raw = chain + _file("a.txt") + END_OF_ARCHIVE

        with pytest.raises(UnsafeTarHeader, match="stacks more than"):
            _names(io.BytesIO(raw))

    def test_a_long_name_plus_long_link_chain_is_fine(self):
        raw = (
            _extended(tarfile.GNUTYPE_LONGLINK, b"target\0")
            + _extended(tarfile.GNUTYPE_LONGNAME, b"real-name.txt\0")
            + _file("short")
            + END_OF_ARCHIVE
        )
        assert _names(io.BytesIO(raw)) == ["real-name.txt"]


class TestSparseMembers:
    def test_an_old_gnu_sparse_member_is_rejected_before_its_map_is_read(self):
        raw = _header("sparse.bin", tarfile.GNUTYPE_SPARSE, 0) + END_OF_ARCHIVE
        with pytest.raises(UnsafeTarHeader, match="sparse"):
            _names(io.BytesIO(raw))

    def test_a_gnu_sparse_1_0_member_is_rejected_before_its_map_is_read(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
            info = tarfile.TarInfo("GNUSparseFile.0/sparse.bin")
            info.size = BLOCK
            info.pax_headers = {
                "GNU.sparse.major": "1",
                "GNU.sparse.minor": "0",
                "GNU.sparse.name": "sparse.bin",
                "GNU.sparse.realsize": "1000000",
            }
            tf.addfile(info, io.BytesIO(b"1\n0\n1\n" + b"\0" * (BLOCK - 6)))
        buf.seek(0)
        with pytest.raises(UnsafeTarHeader, match="sparse"):
            _names(buf)


class TestIteration:
    def test_members_already_passed_are_not_kept(self):
        archive = _tar([(f"f{i}.txt", b"x") for i in range(50)])
        with open_tar(archive) as tf:
            for _member in tf:
                assert len(tf.members) <= 1

    def test_member_bytes_are_still_readable_while_iterating(self):
        archive = _tar([("a.txt", b"alpha"), ("b.txt", b"beta")], mode="w:gz")
        with open_tar(archive) as tf:
            assert [tf.extractfile(member).read() for member in tf] == [b"alpha", b"beta"]


class TestIsTar:
    def test_true_for_a_tar_and_restores_the_position(self):
        archive = _tar([("a.txt", b"x")], mode="w:bz2")
        archive.seek(3)
        assert is_tar(archive)
        assert archive.tell() == 3

    @pytest.mark.parametrize(
        "raw", [b"", b"plain text", gzip.compress(b"plain text"), b"\x1f\x8b broken gzip"]
    )
    def test_false_for_anything_that_is_not_a_readable_tar(self, raw):
        assert not is_tar(io.BytesIO(raw))

    def test_a_hostile_header_raises_instead_of_reading_as_not_a_tar(self):
        raw = _extended(tarfile.GNUTYPE_LONGNAME, b"a", 10 * 1024 * 1024) + END_OF_ARCHIVE
        archive = io.BytesIO(gzip.compress(raw))
        with pytest.raises(UnsafeTarHeader):
            is_tar(archive)
        assert archive.tell() == 0


# --- ZIP central directory ---


def _zip_bytes(count: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(count):
            zf.writestr(f"f{i}.txt", b"")
    return buf.getvalue()


def _eocd_offset(raw: bytes) -> int:
    return raw.rfind(b"PK\x05\x06")


def _with_declared_count(raw: bytes, declared: int) -> bytes:
    """Rewrite the end record's entry counts; the central directory is untouched."""
    data = bytearray(raw)
    eocd = _eocd_offset(raw)
    struct.pack_into("<2H", data, eocd + 8, declared, declared)
    return bytes(data)


def _as_zip64(raw: bytes, declared: int | None = None) -> bytes:
    """Move the end-of-central-directory values into zip64 records, as zipfile
    does past 65535 entries, without writing 65535 entries."""
    eocd = _eocd_offset(raw)
    _, _, _, _, count, directory_size, directory_offset, _ = struct.unpack(
        "<4s4H2LH", raw[eocd : eocd + 22]
    )
    count = count if declared is None else declared
    record = struct.pack(
        "<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, directory_size, directory_offset
    )
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, eocd, 1)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return raw[:eocd] + record + locator + end


class TestZipEntryCount:
    def test_counts_the_entries_of_a_normal_zip(self):
        assert zip_entry_count(io.BytesIO(_zip_bytes(5)), stop_after=100) == 5

    def test_answers_over_the_limit_for_a_zip_past_it(self):
        assert zip_entry_count(io.BytesIO(_zip_bytes(50)), stop_after=3) > 3

    def test_an_over_limit_declared_count_answers_without_walking(self):
        raw = _with_declared_count(_zip_bytes(2), 1000)
        assert zip_entry_count(io.BytesIO(raw), stop_after=10) == 1000

    def test_a_declared_count_that_lies_low_is_not_trusted(self):
        # zipfile ignores the declared count and parses the whole directory
        raw = _with_declared_count(_zip_bytes(6), 1)
        assert len(zipfile.ZipFile(io.BytesIO(raw)).infolist()) == 6
        assert zip_entry_count(io.BytesIO(raw), stop_after=3) == 4

    def test_counts_a_zip64_archive(self):
        raw = _as_zip64(_zip_bytes(5))
        assert len(zipfile.ZipFile(io.BytesIO(raw)).infolist()) == 5
        assert zip_entry_count(io.BytesIO(raw), stop_after=100) == 5

    def test_a_zip64_declared_count_that_lies_low_is_not_trusted(self):
        raw = _as_zip64(_zip_bytes(6), declared=1)
        assert zip_entry_count(io.BytesIO(raw), stop_after=3) == 4

    def test_counts_a_zip_with_a_comment_and_prepended_bytes(self):
        buf = io.BytesIO()
        buf.write(b"#!/bin/sh\nexit 0\n")  # self-extractor style prefix
        with zipfile.ZipFile(buf, "a") as zf:
            zf.comment = b"c" * 300
            for i in range(4):
                zf.writestr(f"f{i}", b"x")
        assert zip_entry_count(io.BytesIO(buf.getvalue()), stop_after=100) == 4

    def test_a_wrecked_directory_stops_the_count_and_is_left_to_zipfile(self):
        raw = bytearray(_zip_bytes(3))
        directory = raw.find(b"PK\x01\x02")
        raw[directory : directory + 4] = b"XXXX"
        assert zip_entry_count(io.BytesIO(bytes(raw)), stop_after=100) == 0
        with pytest.raises(zipfile.BadZipFile):
            zipfile.ZipFile(io.BytesIO(bytes(raw)))

    def test_no_end_record_is_a_bad_zip(self):
        with pytest.raises(zipfile.BadZipFile):
            zip_entry_count(io.BytesIO(b"not a zip at all"), stop_after=10)

    def test_restores_the_file_position(self):
        archive = io.BytesIO(_zip_bytes(3))
        archive.seek(7)
        zip_entry_count(archive, stop_after=10)
        assert archive.tell() == 7
