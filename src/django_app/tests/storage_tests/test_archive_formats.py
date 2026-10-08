"""inspect_archive, the one pre-flight run before anything of an archive is
written, and the name routing that sends a file to it. The tar header bounds it
relies on are covered by test_archive_readers."""

import tarfile
import zipfile
from io import BytesIO

import pytest

from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.archive_unpacking.inspection import inspect_archive
from tables.services.storage_service.archive_unpacking.names import is_archive_name
from tests.storage_tests.in_memory_backend import zip_bytes


@pytest.mark.parametrize(
    ("filename", "is_archive"),
    [
        # every tar alias the old content-sniffing upload extracted must stay routed
        *[
            (name, True)
            for name in (
                "a.zip",
                "a.TGZ",
                "x.tar",
                "x.tgz",
                "x.taz",
                "x.tar.gz",
                "x.tar.bz2",
                "x.tbz",
                "x.tbz2",
                "x.tar.xz",
                "x.txz",
            )
        ],
        ("a.txt", False),
        ("a.docx", False),
        ("a.jar", False),
    ],
)
def test_routing_by_name(filename, is_archive):
    assert is_archive_name(filename) is is_archive


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return buffer.getvalue()


def _tar_of(members, *, tar_format=tarfile.GNU_FORMAT) -> bytes:
    """members: (TarInfo, bytes | None)."""
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tar_format) as archive:
        for info, data in members:
            if data is None:
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, BytesIO(data))
    return buffer.getvalue()


def _typed(name: str, member_type: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = member_type
    return info


def _inspect(raw: bytes, filename="a.zip", *, max_entries=100, free_bytes=10_000):
    return inspect_archive(
        BytesIO(raw),
        filename,
        max_entries=max_entries,
        free_bytes=free_bytes,
        is_blocked=lambda name: name.endswith(".exe"),
    )


def _encrypted_zip() -> bytes:
    """A ZIP with the encryption flag set on the entry and the directory record."""
    raw = bytearray(zip_bytes({"secret.txt": b"data"}))
    raw[6] |= 0x01
    directory = raw.find(b"PK\x01\x02")
    raw[directory + 8] |= 0x01
    return bytes(raw)


def _wrecked_central_directory() -> bytes:
    raw = bytearray(zip_bytes({"a.txt": b"data"}))
    directory = raw.find(b"PK\x01\x02")
    raw[directory + 4 : directory + 40] = b"\xff" * 36  # keep the end record, wreck the entry
    return bytes(raw)


def _truncated_zip() -> bytes:
    raw = zip_bytes({"a.txt": b"x" * 1000})
    return raw[: len(raw) // 2]


def _garbage_end_record() -> bytes:
    raw = bytearray(zip_bytes({"f0.txt": b"", "f1.txt": b""}))
    end_record = raw.rfind(b"PK\x05\x06")
    raw[end_record + 12 : end_record + 20] = b"\xff" * 8  # directory size and offset
    return bytes(raw)


def _with_compression_method(method: int) -> bytes:
    """Set the compression method in the local and the central header of the one entry."""
    data = bytearray(zip_bytes({"a.txt": b"data"}))
    data[8:10] = method.to_bytes(2, "little")
    directory = data.find(b"PK\x01\x02")
    data[directory + 10 : directory + 12] = method.to_bytes(2, "little")
    return bytes(data)


def _symlink_tar() -> bytes:
    link = _typed("link", tarfile.SYMTYPE)
    link.linkname = "/etc/passwd"
    return _tar_of([(link, None)])


def _pax_sparse_tar() -> bytes:
    info = tarfile.TarInfo("sparse.bin")
    info.pax_headers = {
        "GNU.sparse.map": "0,1",
        "GNU.sparse.name": "sparse.bin",
        "GNU.sparse.size": "1",
    }
    return _tar_of([(info, b"x")], tar_format=tarfile.PAX_FORMAT)


def _plain_tar_with_hostile_header() -> bytes:
    info = tarfile.TarInfo("././@LongLink")
    info.type = tarfile.GNUTYPE_LONGNAME
    info.size = 64 * 1024 * 1024  # declared only; a few bytes follow
    return info.tobuf(format=tarfile.GNU_FORMAT) + b"a" * 512 + b"\0" * 1024


def _executables_zip() -> bytes:
    return zip_bytes({"a.exe": b"MZ", "ok.txt": b"x", "b/c.exe": b"MZ"})


class TestInspectAccepts:
    @pytest.mark.parametrize(
        "method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA]
    )
    def test_a_healthy_zip_in_every_supported_method(self, method):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=method) as archive:
            archive.writestr("a.txt", "data" * 100)
        assert _inspect(buffer.getvalue(), "ok.zip") == []

    def test_a_healthy_tar(self):
        assert _inspect(_tar({"a.txt": b"data"}), "a.tar.gz") == []

    def test_plain_bytes_are_not_an_archive(self):
        assert _inspect(b"just plain text", "notes.zip") is None

    def test_returns_directory_entries(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(zipfile.ZipInfo("empty/"), b"")
            archive.writestr("full/a.txt", "x")
        assert _inspect(buffer.getvalue()) == ["empty"]

    def test_restores_the_file_position(self):
        buffer = BytesIO(zip_bytes({"a.txt": b"data"}))
        inspect_archive(
            buffer, "a.zip", max_entries=100, free_bytes=10_000, is_blocked=lambda _: False
        )
        assert buffer.tell() == 0

    def test_an_archive_at_the_entry_limit_passes(self):
        raw = zip_bytes({f"f{index}.txt": b"" for index in range(3)})
        assert _inspect(raw, "three.zip", max_entries=3) == []


@pytest.mark.parametrize(
    ("raw", "filename", "match"),
    [
        (_encrypted_zip(), "secret.zip", "password-protected"),
        (_wrecked_central_directory(), "broken.zip", "damaged or unreadable"),
        (_truncated_zip(), "trunc.zip", "damaged or unreadable"),
        (_garbage_end_record(), "garbage.zip", "damaged or unreadable"),
        (_executables_zip(), "bundle.zip", r"contains executable files: a\.exe, b/c\.exe"),
        (_tar({"../evil.txt": b"x"}), "a.tar.gz", "escapes the target folder"),
        (_symlink_tar(), "a.tar.gz", "symlink"),
        (zip_bytes({}), "empty.zip", "is empty"),
        (zip_bytes({"new\nline.txt": b"x"}), "a.zip", "control character"),
        (zip_bytes({"a": b"file", "a/b": b"child"}), "a.zip", "same name"),
        # zipfile cannot extract deflate64: unpacking would fail with a 500, not a 400
        (_with_compression_method(9), "d64.zip", r"unsupported method \(deflate64\)"),
        (_with_compression_method(99), "odd.zip", r"unsupported method \(99\)"),
        (_pax_sparse_tar(), "sparse.tar.gz", "not a plain file or folder"),
        (_plain_tar_with_hostile_header(), "bomb.tar", "tar header of"),
    ],
    ids=[
        "encrypted",
        "unreadable-directory",
        "truncated",
        "garbage-end-record",
        "executables",
        "zip-slip",
        "symlink",
        "empty",
        "control-character",
        "file-and-folder-same-name",
        "deflate64",
        "unknown-method",
        "pax-sparse",
        "hostile-header-in-plain-tar",
    ],
)
def test_inspect_rejects(raw, filename, match):
    with pytest.raises(ValueError, match=match):
        _inspect(raw, filename)


@pytest.mark.parametrize("member_type", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, b"Z"])
def test_inspect_rejects_a_member_that_is_not_a_file_or_folder(member_type):
    raw = _tar_of([(tarfile.TarInfo("ok.txt"), b"x"), (_typed("odd", member_type), None)])
    with pytest.raises(ValueError, match="not a plain file or folder"):
        _inspect(raw, "odd.tar.gz")


def test_the_unpacked_size_is_bounded_only_by_the_free_space():
    raw = _tar({"big.bin": b"x" * 5_000})
    assert _inspect(raw, "a.tar.gz", free_bytes=5_000) == []
    with pytest.raises(StorageQuotaExceeded):
        _inspect(raw, "a.tar.gz", free_bytes=4_999)


def test_tar_folders_count_toward_the_entry_limit():
    raw = _tar_of([(_typed(f"d{index}", tarfile.DIRTYPE), None) for index in range(3)])
    with pytest.raises(ValueError, match="more than 2 entries"):
        _inspect(raw, "dirs.tar.gz", max_entries=2)


def test_too_many_zip_entries_are_rejected_before_the_directory_is_built(monkeypatch):
    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("ZipFile was built for an over-limit archive")

    monkeypatch.setattr(zipfile.ZipFile, "_RealGetContents", _must_not_run)
    raw = zip_bytes({f"f{index}.txt": b"" for index in range(10)})
    with pytest.raises(ValueError, match="more than 3 entries"):
        _inspect(raw, "many.zip", max_entries=3)
