"""Security properties of archive extraction.

Originally written against `_iter_archive_entries`, the buffer-everything
iterator behind the old multipart upload. That endpoint is gone; the same
guarantees now have to hold for `iter_archive_members_streaming`, which hands
back a reader per member instead of its bytes — so the suite was repointed
rather than deleted. Byte budgets are therefore asserted by draining the
readers, since accounting happens as the member is read.
"""

import tarfile
import zipfile
from io import BytesIO

import pytest

from tables.services.storage_service.archive_limits import (
    ArchiveExtractionGuard,
    ArchiveLimitExceeded,
)
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


@pytest.fixture
def backend(fake_backend):
    """Use fake_backend to access inherited helper methods."""
    return fake_backend


def _names(backend, archive, guard=None) -> list[str]:
    """Iterate without reading member bytes (name-level checks)."""
    return [name for name, _ in backend.iter_archive_members_streaming(archive, guard)]


def _drain(backend, archive, guard=None) -> list[str]:
    """Iterate and read every member, so the guard accounts their bytes."""
    names = []
    for name, reader in backend.iter_archive_members_streaming(archive, guard):
        while reader.read(64 * 1024):
            pass
        names.append(name)
    return names


class TestArchiveKinds:
    # encryption is rejected up front by inspect_archive, not while unpacking

    def test_passes_for_unencrypted_zip(self, backend, sample_zip):
        assert _names(backend, sample_zip)

    def test_passes_for_tar(self, backend, sample_tar):
        assert _names(backend, sample_tar)


class TestIterArchiveMembers:
    def test_yields_zip_contents(self, backend, sample_zip):
        names = _names(backend, sample_zip)
        assert "hello.txt" in names
        assert "sub/world.txt" in names

    def test_yields_tar_contents(self, backend, sample_tar):
        names = _names(backend, sample_tar)
        assert "hello.txt" in names
        assert "sub/world.txt" in names

    def test_member_reader_returns_the_member_bytes(self, backend, sample_zip):
        members = dict(
            (name, reader.read())
            for name, reader in backend.iter_archive_members_streaming(sample_zip)
        )
        assert members["hello.txt"] == b"hello content"

    def test_skips_directories_in_zip(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("dir/", "")  # directory entry
            zf.writestr("dir/file.txt", "content")
        buf.seek(0)
        names = _names(backend, buf)
        assert "dir/file.txt" in names
        assert "dir/" not in names

    def test_raises_for_unsupported_format(self, backend):
        buf = BytesIO(b"this is not an archive at all")
        with pytest.raises(ValueError, match="Unsupported archive"):
            _names(backend, buf)

    def test_raises_for_zip_entry_with_parent_traversal(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/cron.d/x", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            _names(backend, buf)

    def test_raises_for_zip_entry_with_absolute_path(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            _names(backend, buf)

    def test_raises_for_zip_entry_with_unc_style_path(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("\\\\server\\share\\x", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            _names(backend, buf)

    def test_raises_for_entry_name_with_null_byte(self, backend):
        # zipfile silently truncates member names at a null byte before they
        # ever reach the archive, so this checks the sanitizer directly
        # rather than round-tripping through a real ZIP/TAR file.
        with pytest.raises(ValueError, match="null byte"):
            backend._sanitize_archive_member_name("evil\x00.txt")

    def test_raises_for_tar_entry_with_parent_traversal(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            content = b"evil content"
            info = tarfile.TarInfo(name="../evil")
            info.size = len(content)
            tf.addfile(info, BytesIO(content))
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            _names(backend, buf)

    def test_raises_for_tar_symlink_member_even_with_safe_name(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="safe_name.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../etc/passwd"
            tf.addfile(info)
        buf.seek(0)
        with pytest.raises(ValueError, match="symlink or hardlink"):
            _names(backend, buf)

    def test_raises_for_tar_hardlink_member_even_with_safe_name(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="safe_name.txt")
            info.type = tarfile.LNKTYPE
            info.linkname = "../../etc/passwd"
            tf.addfile(info)
        buf.seek(0)
        with pytest.raises(ValueError, match="symlink or hardlink"):
            _names(backend, buf)

    def test_allows_legitimate_nested_entry(self, backend, sample_zip):
        assert "sub/world.txt" in _names(backend, sample_zip)


class TestIterArchiveMembersLimits:
    """Extraction must refuse to run past its budget."""

    def _guard(self, *, max_entries=1_000, max_total_bytes=10_000_000):
        return ArchiveExtractionGuard(
            max_entries=max_entries, max_total_bytes=max_total_bytes
        )

    def test_rejects_zip_past_the_entry_cap(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(10):
                zf.writestr(f"f{i}.txt", "tiny")
        buf.seek(0)

        with pytest.raises(ValueError, match="entries"):
            _names(backend, buf, self._guard(max_entries=5))

    def test_rejects_zip_past_the_byte_budget(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", b"\0" * 500_000)
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            _drain(backend, buf, self._guard(max_total_bytes=1_000))

    def test_rejects_tar_past_the_byte_budget(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            payload = b"\0" * 500_000
            info = tarfile.TarInfo("zeros.bin")
            info.size = len(payload)
            tf.addfile(info, BytesIO(payload))
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            _drain(backend, buf, self._guard(max_total_bytes=1_000))

    def test_byte_budget_spans_all_entries_not_each_one(self, backend):
        """Three 400-byte members are each legal under a 1000-byte total."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(3):
                zf.writestr(f"f{i}.txt", "x" * 400)
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            _drain(backend, buf, self._guard(max_total_bytes=1_000))

    def test_allows_an_archive_inside_its_budget(self, backend, sample_zip):
        assert len(_drain(backend, sample_zip, self._guard())) == 2

    def test_applies_a_default_guard_when_none_is_injected(self, backend, sample_zip):
        assert len(_drain(backend, sample_zip)) == 2


def _tar_of(members, *, tar_format=tarfile.GNU_FORMAT) -> BytesIO:
    """members: (name, member type, bytes or None)."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tar_format) as tf:
        for name, member_type, data in members:
            info = tarfile.TarInfo(name)
            info.type = member_type
            if data is None:
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, BytesIO(data))
    buf.seek(0)
    return buf


class TestStreamingTarHeadersAndTypes:
    """The streaming iterator guards itself too, not only the pre-flight before it.
    Uses its own backend (only the inherited iterator is exercised)."""

    backend = InMemoryStorageBackend()

    @pytest.mark.parametrize("tar_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_a_long_name_header_bomb_is_rejected(self, tar_format):
        archive = _tar_of([("a" * (1024 * 1024), tarfile.REGTYPE, b"x")], tar_format=tar_format)
        with pytest.raises(ValueError, match="tar header of"):
            _names(self.backend, archive)

    @pytest.mark.parametrize("tar_format", [tarfile.GNU_FORMAT, tarfile.PAX_FORMAT])
    def test_long_nested_names_stream_as_before(self, tar_format):
        deep = "/".join(["a-rather-long-folder-name"] * 10) + "/file-" + "n" * 200 + ".txt"
        archive = _tar_of(
            [("empty", tarfile.DIRTYPE, None), (deep, tarfile.REGTYPE, b"deep")],
            tar_format=tar_format,
        )
        assert _drain(self.backend, archive) == [deep]

    @pytest.mark.parametrize("member_type", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
    def test_a_device_or_fifo_member_is_rejected(self, member_type):
        archive = _tar_of([("ok.txt", tarfile.REGTYPE, b"x"), ("dev", member_type, None)])
        with pytest.raises(ValueError, match="not a plain file or folder"):
            _names(self.backend, archive)

    def test_every_member_counts_toward_the_entry_cap_folders_too(self):
        archive = _tar_of([(f"d{i}", tarfile.DIRTYPE, None) for i in range(3)])
        guard = ArchiveExtractionGuard(max_entries=2, max_total_bytes=1_000)
        with pytest.raises(ArchiveLimitExceeded, match="more than 2 entries"):
            _names(self.backend, archive, guard)
