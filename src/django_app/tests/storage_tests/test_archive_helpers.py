import tarfile
import zipfile
from io import BytesIO

import pytest


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
