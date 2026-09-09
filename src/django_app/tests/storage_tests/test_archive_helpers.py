import tarfile
import zipfile
from io import BytesIO

import pytest

from tables.services.storage_service.archive_limits import ArchiveExtractionGuard


@pytest.fixture
def backend(fake_backend):
    """Use fake_backend to access inherited helper methods."""
    return fake_backend


class TestCheckArchivePassword:
    def test_raises_for_encrypted_zip(self, backend, password_zip):
        with pytest.raises(ValueError, match="protected"):
            backend._check_archive_password(password_zip, "encrypted.zip")

    def test_passes_for_unencrypted_zip(self, backend, sample_zip):
        backend._check_archive_password(sample_zip, "sample.zip")  # no error

    def test_skips_non_zip(self, backend, sample_tar):
        backend._check_archive_password(sample_tar, "sample.tar")  # no error


class TestIterArchiveEntries:
    def test_yields_zip_contents(self, backend, sample_zip):
        entries = list(backend._iter_archive_entries(sample_zip))
        names = [name for name, _ in entries]
        assert "hello.txt" in names
        assert "sub/world.txt" in names

    def test_yields_tar_contents(self, backend, sample_tar):
        entries = list(backend._iter_archive_entries(sample_tar))
        names = [name for name, _ in entries]
        assert "hello.txt" in names
        assert "sub/world.txt" in names

    def test_skips_directories_in_zip(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("dir/", "")  # directory entry
            zf.writestr("dir/file.txt", "content")
        buf.seek(0)
        entries = list(backend._iter_archive_entries(buf))
        names = [name for name, _ in entries]
        assert "dir/file.txt" in names
        assert "dir/" not in names

    def test_raises_for_unsupported_format(self, backend):
        buf = BytesIO(b"this is not an archive at all")
        with pytest.raises(ValueError, match="Unsupported archive"):
            list(backend._iter_archive_entries(buf))

    def test_raises_for_zip_entry_with_parent_traversal(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/cron.d/x", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            list(backend._iter_archive_entries(buf))

    def test_raises_for_zip_entry_with_absolute_path(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            list(backend._iter_archive_entries(buf))

    def test_raises_for_zip_entry_with_unc_style_path(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("\\\\server\\share\\x", "evil content")
        buf.seek(0)
        with pytest.raises(ValueError, match="escapes the target folder"):
            list(backend._iter_archive_entries(buf))

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
            list(backend._iter_archive_entries(buf))

    def test_raises_for_tar_symlink_member_even_with_safe_name(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="safe_name.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../etc/passwd"
            tf.addfile(info)
        buf.seek(0)
        with pytest.raises(ValueError, match="symlink or hardlink"):
            list(backend._iter_archive_entries(buf))

    def test_raises_for_tar_hardlink_member_even_with_safe_name(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="safe_name.txt")
            info.type = tarfile.LNKTYPE
            info.linkname = "../../etc/passwd"
            tf.addfile(info)
        buf.seek(0)
        with pytest.raises(ValueError, match="symlink or hardlink"):
            list(backend._iter_archive_entries(buf))

    def test_allows_legitimate_nested_entry(self, backend, sample_zip):
        entries = list(backend._iter_archive_entries(sample_zip))
        names = [name for name, _ in entries]
        assert "sub/world.txt" in names


class TestIterArchiveEntriesLimits:
    """_iter_archive_entries must refuse to buffer an archive past its budget."""

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
            list(backend._iter_archive_entries(buf, guard=self._guard(max_entries=5)))

    def test_rejects_zip_past_the_byte_budget(self, backend):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", b"\0" * 500_000)
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            list(
                backend._iter_archive_entries(
                    buf, guard=self._guard(max_total_bytes=1_000)
                )
            )

    def test_rejects_tar_past_the_byte_budget(self, backend):
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            payload = b"\0" * 500_000
            info = tarfile.TarInfo("zeros.bin")
            info.size = len(payload)
            tf.addfile(info, BytesIO(payload))
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            list(
                backend._iter_archive_entries(
                    buf, guard=self._guard(max_total_bytes=1_000)
                )
            )

    def test_byte_budget_spans_all_entries_not_each_one(self, backend):
        """Three 400-byte members are each legal under a 1000-byte total."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(3):
                zf.writestr(f"f{i}.txt", "x" * 400)
        buf.seek(0)

        with pytest.raises(ValueError, match="bytes"):
            list(
                backend._iter_archive_entries(
                    buf, guard=self._guard(max_total_bytes=1_000)
                )
            )

    def test_allows_an_archive_inside_its_budget(self, backend, sample_zip):
        entries = list(backend._iter_archive_entries(sample_zip, guard=self._guard()))

        assert len(entries) == 2

    def test_applies_a_default_guard_when_none_is_injected(self, backend, sample_zip):
        entries = list(backend._iter_archive_entries(sample_zip))

        assert len(entries) == 2
