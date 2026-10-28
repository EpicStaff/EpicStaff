"""Comprehensive path traversal and normalization tests.

These tests verify that path traversal attacks are rejected at the permission
check stage (before reaching the S3 client), and that path normalization works
correctly across the storage API.
"""

import os
import sys

import pytest

from epicstaff_storage import StoragePermissionError, check_storage_permission

# Access the storage module's state for assertion purposes
storage_module = sys.modules["epicstaff_storage.storage"]


def _clear_cache():
    """Clear the module-level __cache at module scope (avoids name mangling)."""
    storage_module.__cache.clear()


class TestMutationOperationsRejectTraversal:
    """Test that mutation operations reject traversal paths without reaching S3."""

    def test_write_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """write() should reject ../org_2/secret.txt even without STORAGE_ALLOWED_PATHS."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        # Clear the cache so the new org prefix is read
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.write("../org_2/secret.txt", "nope")

        # The bad key never reaches the fake client
        assert fake_client.objects == {}

    def test_write_bytes_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """write_bytes() should reject ../org_2/secret.txt even without STORAGE_ALLOWED_PATHS."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.write_bytes("../org_2/secret.txt", b"nope")

        assert fake_client.objects == {}

    def test_mkdir_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """mkdir() should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.mkdir("../org_2/folder")

        assert fake_client.objects == {}

    def test_delete_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """delete() should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.delete("../org_2/secret.txt")

        assert fake_client.objects == {}

    def test_copy_src_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """copy() source should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.copy("../org_2/secret.txt", "dest.txt")

        assert fake_client.objects == {}

    def test_copy_dst_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """copy() destination should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()
        # Set up a source file first
        storage.write("source.txt", "data")
        fake_client.objects.clear()  # Reset to track only the copy attempt

        with pytest.raises(StoragePermissionError):
            storage.copy("source.txt", "../org_2/secret.txt")

        # No copy operation was added
        assert fake_client.objects == {}

    def test_move_src_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """move() source should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.move("../org_2/secret.txt", "dest.txt")

        assert fake_client.objects == {}

    def test_move_dst_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """move() destination should reject traversal paths."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()
        # Set up a source file first
        storage.write("source.txt", "data")
        fake_client.objects.clear()  # Reset to track only the move attempt

        with pytest.raises(StoragePermissionError):
            storage.move("source.txt", "../org_2/secret.txt")

        # No move operation was performed (no delete either)
        assert fake_client.objects == {}

    def test_delete_folder_rejects_traversal_when_no_allowlist(self, monkeypatch, storage, fake_client):
        """delete_folder() should reject traversal paths with StoragePermissionError,
        same as every other mutating operation — ValueError is reserved for the
        empty/root-path argument-error case, not for traversal."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.delete_folder("../org_2/folder")

        assert fake_client.objects == {}


class TestReadOperationsRejectTraversal:
    """Test that read operations reject traversal before calling the S3 client."""

    def test_read_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """read() should reject ../org_2/secret.txt before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.read("../org_2/secret.txt")

        # The client was never called
        assert not hasattr(fake_client, "_get_object_called")

    def test_read_bytes_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """read_bytes() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.read_bytes("../org_2/secret.txt")

    def test_exists_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """exists() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.exists("../org_2/secret.txt")

    def test_info_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """info() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.info("../org_2/secret.txt")

    def test_list_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """list() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.list("../org_2")

    def test_walk_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """walk() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.walk("../org_2")

    def test_as_local_rejects_traversal_before_calling_client(self, monkeypatch, storage, fake_client):
        """as_local() should reject traversal paths before calling the client."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            with storage.as_local("../org_2/secret.txt"):
                pass


class TestPathEquivalence:
    """Test that equivalent path forms are canonicalized correctly."""

    @pytest.mark.parametrize(
        "path,expected_key",
        [
            ("a/../b", "b"),  # traversal cancelled -> "b"
            ("./a", "a"),  # current-directory prefix -> "a"
            ("a//b", "a/b"),  # double slash -> "a/b"
            ("/a/b", "a/b"),  # leading slash stripped -> "a/b"
            ("a/b", "a/b"),  # already canonical -> "a/b"
        ],
    )
    def test_paths_canonicalize_correctly(self, storage, fake_client, path, expected_key):
        """Each path should canonicalize to its expected form."""
        fake_client.objects.clear()  # Start fresh for each parametrized test
        storage.write(path, "data")
        # Should have exactly one key in the fake client
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == expected_key

    def test_empty_path_is_valid_with_allow_empty(self, storage, fake_client):
        """Empty path should be allowed by _normalize_key and produce empty string."""
        storage.write("", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == ""


class TestTrailingSlashPreservation:
    """Test that trailing slashes are preserved in stored keys."""

    def test_trailing_slash_preserved_in_write(self, storage, fake_client):
        """write("folder/", ...) should preserve the trailing slash in the stored key."""
        storage.write("folder/", "x")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "folder/"

    def test_no_trailing_slash_not_added(self, storage, fake_client):
        """write("folder", ...) should not add a trailing slash."""
        storage.write("folder", "x")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "folder"

    def test_trailing_slash_preserved_with_org_prefix(self, monkeypatch, storage, fake_client):
        """Trailing slash should be preserved even with STORAGE_ORG_PREFIX."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        storage.write("folder/", "x")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "org_1/folder/"


class TestDotfileAllowance:
    """Test that dotfile names are allowed (they don't trigger traversal guards)."""

    def test_double_dot_filename_is_allowed(self, storage, fake_client):
        """A filename like ..env should be allowed (it's not a path segment)."""
        storage.write("..env", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "..env"

    def test_double_dot_in_folder_name_is_allowed(self, storage, fake_client):
        """A folder component like folder..name should be allowed."""
        storage.write("folder..name/file.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "folder..name/file.txt"


class TestNullByteRejection:
    """Test that null bytes in paths are rejected."""

    def test_null_byte_in_path_raises_storage_permission_error(self, storage, fake_client):
        """Paths with null bytes should be rejected as StoragePermissionError."""
        with pytest.raises(StoragePermissionError):
            storage.write("a\x00b.txt", "data")

        assert fake_client.objects == {}

    def test_null_byte_in_read_raises_storage_permission_error(self, storage, fake_client):
        """Reading paths with null bytes should be rejected."""
        with pytest.raises(StoragePermissionError):
            storage.read("a\x00b.txt")


class TestBackslashRewriting:
    """Test that backslashes are rewritten to forward slashes."""

    def test_backslash_rewritten_to_forward_slash(self, storage, fake_client):
        """Backslashes in paths should be rewritten to forward slashes."""
        storage.write("a\\b.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "a/b.txt"

    def test_backslash_traversal_attempt_rejected(self, monkeypatch, storage, fake_client):
        """Path traversal using backslashes like ..\\x should be rejected."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        with pytest.raises(StoragePermissionError):
            storage.write("..\\x", "nope")

        assert fake_client.objects == {}

    def test_mixed_slash_styles_are_normalized(self, storage, fake_client):
        """Paths with mixed slash styles should be normalized."""
        storage.write("a\\b/c\\d.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "a/b/c/d.txt"


class TestReservedPathWithTraversal:
    """Test that reserved paths are detected after normalization (fourth duplicate)."""

    def test_reserved_path_detected_after_traversal_normalization(self, storage, fake_client):
        """check_storage_permission should detect .recycle-bin after normalizing a/../.recycle-bin."""
        with pytest.raises(StoragePermissionError) as exc_info:
            check_storage_permission("read", "a/../.recycle-bin/x")

        assert ".recycle-bin" in str(exc_info.value)
        assert "deleted files" in str(exc_info.value)


class TestEdgeCases:
    """Additional edge cases for path normalization."""

    def test_multiple_slashes_normalized(self, storage, fake_client):
        """Multiple consecutive slashes should be normalized to one."""
        storage.write("a///b////c.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "a/b/c.txt"

    def test_dot_directory_in_middle_removed(self, storage, fake_client):
        """./  in the middle of a path should be normalized away."""
        storage.write("a/./b.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "a/b.txt"

    def test_leading_dot_removed_but_dotfiles_preserved(self, storage, fake_client):
        """Leading ./ should be removed, but dotfiles like .hidden should be preserved."""
        storage.write("./.hidden", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == ".hidden"

    def test_leading_slash_stripped_with_org_prefix(self, monkeypatch, storage, fake_client):
        """Leading slashes should be stripped before adding org prefix."""
        monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_1")
        _clear_cache()

        storage.write("/file.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "org_1/file.txt"

    def test_complex_normalization(self, storage, fake_client):
        """Test a complex path that exercises multiple normalization rules."""
        storage.write("/a/../b/./c//d.txt", "data")
        keys = list(fake_client.objects.keys())
        assert len(keys) == 1
        assert keys[0] == "b/c/d.txt"
