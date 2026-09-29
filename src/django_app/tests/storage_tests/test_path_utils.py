import pytest

from tables.services.storage_service.path_utils import sanitize_storage_path


class TestSanitizeStoragePath:
    def test_empty_allowed(self):
        assert sanitize_storage_path("", allow_empty=True) == ""

    def test_empty_not_allowed_raises(self):
        with pytest.raises(ValueError):
            sanitize_storage_path("", allow_empty=False)

    def test_root_slash_normalizes_to_empty(self):
        assert sanitize_storage_path("/", allow_empty=True) == ""

    def test_simple_relative_path_preserved(self):
        assert sanitize_storage_path("a/b", allow_empty=True) == "a/b"

    def test_leading_parent_traversal_raises(self):
        with pytest.raises(ValueError, match="escapes the target folder"):
            sanitize_storage_path("../etc/passwd", allow_empty=True)

    def test_traversal_that_escapes_root_after_normalization_raises(self):
        with pytest.raises(ValueError, match="escapes the target folder"):
            sanitize_storage_path("a/../../etc", allow_empty=True)

    def test_internal_traversal_within_bounds_collapses(self):
        assert sanitize_storage_path("a/../b", allow_empty=True) == "b"

    def test_double_dot_as_filename_substring_preserved(self):
        assert sanitize_storage_path("file..txt", allow_empty=True) == "file..txt"

    def test_leading_double_dot_as_filename_prefix_preserved(self):
        assert sanitize_storage_path("..hidden", allow_empty=True) == "..hidden"

    def test_null_byte_raises(self):
        with pytest.raises(ValueError, match="null byte"):
            sanitize_storage_path("path/with\x00null", allow_empty=True)

    def test_bare_parent_segment_raises(self):
        with pytest.raises(ValueError, match="escapes the target folder"):
            sanitize_storage_path("..", allow_empty=True)
