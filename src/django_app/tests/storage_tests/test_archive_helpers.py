import zipfile
from io import BytesIO

import pytest


@pytest.fixture
def backend(local_backend):
    """Use local_backend to access inherited helper methods."""
    return local_backend


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
