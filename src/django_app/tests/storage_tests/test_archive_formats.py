import tarfile
import zipfile
from io import BytesIO

import pytest

from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.archive_formats import inspect_archive, is_archive_name


def test_routing():
    assert is_archive_name("a.zip")
    assert is_archive_name("a.tar.gz")
    assert is_archive_name("a.TGZ")
    assert is_archive_name("a.tbz")
    assert is_archive_name("a.taz")
    assert not is_archive_name("a.txt")
    assert not is_archive_name("a.docx")
    assert not is_archive_name("a.jar")


def test_every_tar_alias_the_content_sniffing_path_accepted_is_still_routed():
    # the non-streaming upload detected archives by content, so these aliases used to
    # be extracted; extension routing has to name them explicitly or they regress
    for name in ("x.tar", "x.tgz", "x.taz", "x.tar.gz", "x.tar.bz2", "x.tbz", "x.tbz2", "x.tar.xz", "x.txz"):
        assert is_archive_name(name), name


def _zip(name: str, body: str) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, body)
    buf.seek(0)
    return buf


def _tar(members: dict[str, bytes]) -> BytesIO:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    buf.seek(0)
    return buf


def _encrypted_zip() -> BytesIO:
    """A ZIP with the encryption flag set on the entry and the directory record."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("secret.txt", "data")
    raw = bytearray(buf.getvalue())
    raw[6] |= 0x01
    cd = raw.find(b"PK\x01\x02")
    if cd >= 0:
        raw[cd + 8] |= 0x01
    return BytesIO(bytes(raw))


def _inspect(file_object, filename="a.zip", *, max_entries=100, free_bytes=10_000):
    return inspect_archive(
        file_object,
        filename,
        max_entries=max_entries,
        free_bytes=free_bytes,
        is_blocked=lambda name: name.endswith(".exe"),
    )


class TestInspectArchive:
    """The one pre-flight run before anything of an archive is written."""

    def test_accepts_a_healthy_zip_and_tar(self):
        assert _inspect(_zip("a.txt", "data")) == []
        assert _inspect(_tar({"a.txt": b"data"}), "a.tar.gz") == []

    def test_false_for_plain_bytes(self):
        assert _inspect(BytesIO(b"just plain text"), "notes.zip") is None

    def test_rejects_an_encrypted_zip(self):
        with pytest.raises(ValueError, match="password-protected"):
            _inspect(_encrypted_zip(), "secret.zip")

    def test_rejects_an_unreadable_central_directory(self):
        raw = bytearray(_zip("a.txt", "data").getvalue())
        cd = raw.find(b"PK\x01\x02")
        raw[cd + 4 : cd + 40] = b"\xff" * 36  # keep the EOCD, wreck the entry
        with pytest.raises(ValueError, match="damaged or unreadable"):
            _inspect(BytesIO(bytes(raw)), "broken.zip")

    def test_lists_every_executable_inside(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.exe", "MZ")
            zf.writestr("ok.txt", "x")
            zf.writestr("b/c.exe", "MZ")
        buf.seek(0)
        with pytest.raises(ValueError, match=r"contains executable files: a\.exe, b/c\.exe"):
            _inspect(buf, "bundle.zip")

    def test_rejects_a_member_escaping_the_folder(self):
        with pytest.raises(ValueError):
            _inspect(_tar({"../evil.txt": b"x"}), "a.tar.gz")

    def test_rejects_a_symlink(self):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)
        buf.seek(0)
        with pytest.raises(ValueError, match="symlink"):
            _inspect(buf, "a.tar")

    def test_too_many_entries(self):
        with pytest.raises(ValueError, match="more than 1 entries"):
            _inspect(_tar({"a": b"1", "b": b"2"}), "a.tar.gz", max_entries=1)

    def test_unpacked_size_is_bounded_only_by_free_space(self):
        archive = _tar({"big.bin": b"x" * 5_000})
        assert _inspect(archive, "a.tar.gz", free_bytes=5_000) == []
        archive.seek(0)
        with pytest.raises(StorageQuotaExceeded):
            _inspect(archive, "a.tar.gz", free_bytes=4_999)

    def test_restores_the_file_position(self):
        buf = _zip("a.txt", "data")
        _inspect(buf)
        assert buf.tell() == 0

    def test_returns_directory_entries(self):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(zipfile.ZipInfo("empty/"), b"")
            zf.writestr("full/a.txt", "x")
        buf.seek(0)
        assert _inspect(buf) == ["empty"]

    def test_rejects_an_empty_archive(self):
        with pytest.raises(ValueError, match="is empty"):
            _inspect(BytesIO(_zip_bytes({})), "empty.zip")

    def test_a_truncated_archive_is_damaged_not_a_plain_file(self):
        raw = _zip_bytes({"a.txt": b"x" * 1000})
        with pytest.raises(ValueError, match="damaged or unreadable"):
            _inspect(BytesIO(raw[: len(raw) // 2]), "trunc.zip")

    def test_rejects_control_characters_in_member_names(self):
        with pytest.raises(ValueError, match="control character"):
            _inspect(BytesIO(_zip_bytes({"new\nline.txt": b"x"})))

    def test_rejects_a_file_and_folder_with_the_same_name(self):
        with pytest.raises(ValueError, match="same name"):
            _inspect(BytesIO(_zip_bytes({"a": b"file", "a/b": b"child"})))


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()
