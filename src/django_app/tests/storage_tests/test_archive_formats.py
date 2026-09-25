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


# --- hostile headers and member types (all rejected as ValueError = 400) ---


def _tar_of(members, *, tar_format=tarfile.GNU_FORMAT, mode="w:gz") -> BytesIO:
    """members: (TarInfo, bytes | None)."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode=mode, format=tar_format) as tf:
        for info, data in members:
            if data is None:
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, BytesIO(data))
    buf.seek(0)
    return buf


def _typed(name: str, member_type: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = member_type
    return info


class TestInspectHostileTar:
    @pytest.mark.parametrize("tar_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_a_long_name_header_bomb_is_rejected(self, tar_format):
        # 1 MiB name (over the 64 KiB bound) in about 1 KiB of .tar.gz
        archive = _tar_of([(tarfile.TarInfo("a" * (1024 * 1024)), b"x")], tar_format=tar_format)
        with pytest.raises(ValueError, match="tar header of"):
            _inspect(archive, "bomb.tar.gz")

    @pytest.mark.parametrize("tar_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_long_nested_names_and_empty_folders_still_unpack(self, tar_format):
        deep = "/".join(["a-rather-long-folder-name"] * 10)
        archive = _tar_of(
            [
                (_typed("empty", tarfile.DIRTYPE), None),
                (_typed(deep, tarfile.DIRTYPE), None),
                (tarfile.TarInfo(f"{deep}/file-" + "n" * 200 + ".txt"), b"data"),
            ],
            tar_format=tar_format,
        )
        assert _inspect(archive, "ok.tar.gz") == sorted(["empty", deep])

    @pytest.mark.parametrize(
        "member_type", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, b"Z"]
    )
    def test_a_member_that_is_not_a_file_or_folder_is_rejected(self, member_type):
        archive = _tar_of([(tarfile.TarInfo("ok.txt"), b"x"), (_typed("odd", member_type), None)])
        with pytest.raises(ValueError, match="not a plain file or folder"):
            _inspect(archive, "odd.tar.gz")

    def test_a_pax_sparse_member_is_rejected(self):
        info = tarfile.TarInfo("sparse.bin")
        info.pax_headers = {
            "GNU.sparse.map": "0,1",
            "GNU.sparse.name": "sparse.bin",
            "GNU.sparse.size": "1",
        }
        archive = _tar_of([(info, b"x")], tar_format=tarfile.PAX_FORMAT)
        with pytest.raises(ValueError, match="not a plain file or folder"):
            _inspect(archive, "sparse.tar.gz")

    def test_folders_count_toward_the_entry_limit(self):
        archive = _tar_of([(_typed(f"d{i}", tarfile.DIRTYPE), None) for i in range(3)])
        with pytest.raises(ValueError, match="more than 2 entries"):
            _inspect(archive, "dirs.tar.gz", max_entries=2)

    def test_a_hostile_header_in_a_plain_tar_is_not_stored_as_a_plain_file(self):
        info = tarfile.TarInfo("././@LongLink")
        info.type = tarfile.GNUTYPE_LONGNAME
        info.size = 64 * 1024 * 1024  # declared only; a few bytes follow
        raw = info.tobuf(format=tarfile.GNU_FORMAT) + b"a" * 512 + b"\0" * 1024
        with pytest.raises(ValueError, match="tar header of"):
            _inspect(BytesIO(raw), "bomb.tar")


def _zip_with_entries(count: int) -> bytes:
    return _zip_bytes({f"f{i}.txt": b"" for i in range(count)})


class TestInspectZipDirectory:
    def test_too_many_entries_are_rejected_before_the_directory_is_built(self, monkeypatch):
        def _must_not_run(*_args, **_kwargs):
            raise AssertionError("ZipFile was built for an over-limit archive")

        monkeypatch.setattr(zipfile.ZipFile, "_RealGetContents", _must_not_run)
        with pytest.raises(ValueError, match="more than 3 entries"):
            _inspect(BytesIO(_zip_with_entries(10)), "many.zip", max_entries=3)

    def test_a_low_declared_count_does_not_hide_the_real_one(self):
        raw = bytearray(_zip_with_entries(10))
        eocd = raw.rfind(b"PK\x05\x06")
        raw[eocd + 8 : eocd + 12] = b"\x01\x00\x01\x00"  # "1 entry"
        with pytest.raises(ValueError, match="more than 3 entries"):
            _inspect(BytesIO(bytes(raw)), "liar.zip", max_entries=3)

    def test_an_archive_at_the_limit_passes(self):
        assert _inspect(BytesIO(_zip_with_entries(3)), "three.zip", max_entries=3) == []

    def test_a_garbage_end_record_is_damaged(self):
        raw = bytearray(_zip_with_entries(2))
        eocd = raw.rfind(b"PK\x05\x06")
        raw[eocd + 12 : eocd + 20] = b"\xff" * 8  # directory size and offset
        with pytest.raises(ValueError, match="damaged or unreadable"):
            _inspect(BytesIO(bytes(raw)), "garbage.zip")


def _with_compression_method(raw: bytes, method: int) -> bytes:
    """Set the compression method in the local and the central header of the one entry."""
    data = bytearray(raw)
    data[8:10] = method.to_bytes(2, "little")
    directory = data.find(b"PK\x01\x02")
    data[directory + 10 : directory + 12] = method.to_bytes(2, "little")
    return bytes(data)


class TestInspectZipCompression:
    def test_deflate64_is_rejected_before_extraction(self):
        raw = _with_compression_method(_zip_bytes({"a.txt": b"data"}), 9)
        with zipfile.ZipFile(BytesIO(raw)) as zf, pytest.raises(NotImplementedError):
            zf.open("a.txt")  # what extraction would hit: a 500, not a 400

        with pytest.raises(ValueError, match=r"unsupported method \(deflate64\)"):
            _inspect(BytesIO(raw), "d64.zip")

    def test_an_unknown_method_is_rejected(self):
        raw = _with_compression_method(_zip_bytes({"a.txt": b"data"}), 99)
        with pytest.raises(ValueError, match=r"unsupported method \(99\)"):
            _inspect(BytesIO(raw), "odd.zip")

    @pytest.mark.parametrize(
        "method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA]
    )
    def test_the_supported_methods_pass(self, method):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=method) as zf:
            zf.writestr("a.txt", "data" * 100)
        buf.seek(0)
        assert _inspect(buf, "ok.zip") == []
