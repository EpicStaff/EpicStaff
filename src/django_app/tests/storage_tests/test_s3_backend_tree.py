from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from tables.services.storage_service.s3_backend import S3StorageBackend


def _make_s3_backend() -> S3StorageBackend:
    with patch("tables.services.storage_service.s3_backend.boto3"):
        return S3StorageBackend(
            bucket_name="test",
            access_key="k",
            secret_key="s",
            organization_prefix="",
            endpoint_url=None,
            part_size=16 * 1024 * 1024,
        )


def _page(keys_with_sizes):
    """Build a list_objects_v2 page with curated keys."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return {
        "Contents": [
            {"Key": k, "Size": size, "LastModified": now} for k, size in keys_with_sizes
        ]
    }


class TestS3BackendTree:
    def test_tree_builds_nested_from_flat_keys(self):
        backend = _make_s3_backend()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            _page(
                [
                    ("reports/", 0),
                    ("reports/q1.pdf", 100),
                    ("reports/2025/", 0),
                    ("reports/2025/summary.txt", 50),
                ]
            )
        ]
        backend.client = MagicMock()
        backend.client.get_paginator.return_value = paginator

        root, truncated = backend.list_tree("reports")
        assert truncated is False
        names = sorted(c.name for c in root.children)
        assert names == ["2025", "q1.pdf"]
        year = next(c for c in root.children if c.name == "2025")
        assert year.children[0].name == "summary.txt"

    def test_tree_max_depth_truncates_deep_keys_but_keeps_ancestors(self):
        """Regression: all keys below max_depth used to disappear entirely."""
        backend = _make_s3_backend()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            _page(
                [
                    ("a/b/c/d/e/f/g/", 0),
                ]
            )
        ]
        backend.client = MagicMock()
        backend.client.get_paginator.return_value = paginator

        root, _ = backend.list_tree("", max_depth=2)
        assert len(root.children) == 1
        assert root.children[0].name == "a"
        assert len(root.children[0].children) == 1
        assert root.children[0].children[0].name == "b"
        assert root.children[0].children[0].children == []

    def test_tree_dedups_when_multiple_deep_keys_share_ancestor(self):
        backend = _make_s3_backend()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            _page(
                [
                    ("a/b/c/x.txt", 1),
                    ("a/b/d/y.txt", 1),
                    ("a/b/e/z.txt", 1),
                ]
            )
        ]
        backend.client = MagicMock()
        backend.client.get_paginator.return_value = paginator

        root, _ = backend.list_tree("", max_depth=2)
        assert root.children[0].name == "a"
        assert root.children[0].children[0].name == "b"
        assert root.children[0].children[0].children == []

    def test_tree_honors_max_entries_cap(self):
        backend = _make_s3_backend()
        paginator = MagicMock()
        paginator.paginate.return_value = [_page([(f"f{i}.txt", 1) for i in range(20)])]
        backend.client = MagicMock()
        backend.client.get_paginator.return_value = paginator

        root, truncated = backend.list_tree("", max_entries=5)
        assert truncated is True
        assert len(root.children) <= 5


class TestS3BackendPathValidation:
    """Tests for path validation in mkdir() and info() methods (step 4)."""

    def test_mkdir_path_traversal_with_double_dot_raises_value_error(self):
        """Verify mkdir() with .. path traversal raises ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("../malicious")

    def test_mkdir_path_traversal_in_middle_raises_value_error(self):
        """Verify mkdir() with .. in the middle raises ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("folder/../../escape")

    def test_mkdir_null_byte_in_path_raises_value_error(self):
        """Verify mkdir() with null byte raises ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("folder\x00malicious")

    @pytest.mark.parametrize("invalid_path", [
        "../etc/passwd",
        "../../root",
        "files/../../../etc/passwd",
        "/absolute/path",
    ])
    def test_mkdir_various_traversal_attempts_raise_value_error(self, invalid_path):
        """Verify mkdir() rejects various path traversal attempts."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir(invalid_path)

    def test_mkdir_minio_invalid_object_name_raises_value_error(self):
        """Verify mkdir() converts MinIO InvalidArgument error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "InvalidArgument"}}
        backend.client.put_object.side_effect = ClientError(error_response, "PutObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("some_path")

    def test_mkdir_minio_key_too_long_raises_value_error(self):
        """Verify mkdir() converts KeyTooLongError to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "KeyTooLongError"}}
        backend.client.put_object.side_effect = ClientError(error_response, "PutObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("some_path")

    def test_mkdir_minio_bad_request_raises_value_error(self):
        """Verify mkdir() converts MinIO 400 error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "400"}}
        backend.client.put_object.side_effect = ClientError(error_response, "PutObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("some_path")

    def test_mkdir_minio_xminio_invalid_object_name_raises_value_error(self):
        """Verify mkdir() converts XMinioInvalidObjectName error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "XMinioInvalidObjectName"}}
        backend.client.put_object.side_effect = ClientError(error_response, "PutObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.mkdir("some_path")

    def test_mkdir_other_client_error_is_reraised(self):
        """Verify mkdir() re-raises other ClientErrors."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "NoSuchBucket"}}
        backend.client.put_object.side_effect = ClientError(error_response, "PutObject")

        with pytest.raises(ClientError):
            backend.mkdir("some_path")

    def test_mkdir_valid_path_succeeds(self):
        """Verify mkdir() succeeds with valid paths."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        backend.mkdir("valid/folder/path")

        backend.client.put_object.assert_called_once()

    def test_info_path_traversal_raises_value_error(self):
        """Verify info() with .. path traversal raises ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("../escape")

    def test_info_null_byte_raises_value_error(self):
        """Verify info() with null byte raises ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("file\x00name")

    @pytest.mark.parametrize("invalid_path", [
        "../../etc/passwd",
        "/absolute",
        "files/../../../etc",
    ])
    def test_info_various_traversal_attempts_raise_value_error(self, invalid_path):
        """Verify info() rejects various path traversal attempts."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info(invalid_path)

    def test_info_minio_invalid_argument_error_on_file_check_raises_value_error(self):
        """Verify info() converts InvalidArgument error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "InvalidArgument"}}
        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("file")

    def test_info_minio_key_too_long_error_raises_value_error(self):
        """Verify info() converts KeyTooLongError to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "KeyTooLongError"}}
        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("file")

    def test_info_minio_bad_request_raises_value_error(self):
        """Verify info() converts 400 error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "400"}}
        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("file")

    def test_info_minio_xminio_invalid_object_name_raises_value_error(self):
        """Verify info() converts XMinioInvalidObjectName error to ValueError."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "XMinioInvalidObjectName"}}
        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")

        with pytest.raises(ValueError, match="Invalid storage path"):
            backend.info("file")

    def test_info_404_error_falls_through_to_next_check(self):
        """Verify info() handles 404 gracefully and tries folder check."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response_404 = {"Error": {"Code": "404"}}
        error_response_404_folder = {"Error": {"Code": "404"}}

        backend.client.head_object.side_effect = [
            ClientError(error_response_404, "HeadObject"),  # File check
            ClientError(error_response_404_folder, "HeadObject"),  # Folder check
        ]
        backend.client.list_objects_v2.return_value = {"Contents": []}

        with pytest.raises(FileNotFoundError):
            backend.info("nonexistent")

    def test_info_other_error_is_reraised(self):
        """Verify info() re-raises non-validation errors."""
        backend = _make_s3_backend()
        backend.client = MagicMock()
        error_response = {"Error": {"Code": "NoSuchBucket"}}
        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")

        with pytest.raises(ClientError):
            backend.info("file")

    def test_info_valid_file_path_succeeds(self):
        """Verify info() succeeds with valid file paths."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        backend.client.head_object.return_value = {
            "ContentLength": 100,
            "ContentType": "text/plain",
            "LastModified": now,
        }

        result = backend.info("valid_file.txt")

        assert result.name == "valid_file.txt"
        assert result.size == 100

    def test_info_valid_folder_path_succeeds(self):
        """Verify info() succeeds with valid folder paths."""
        backend = _make_s3_backend()
        backend.client = MagicMock()

        now = datetime(2024, 1, 1, tzinfo=timezone.utc)
        error_response = {"Error": {"Code": "404"}}

        backend.client.head_object.side_effect = ClientError(error_response, "HeadObject")
        backend.client.list_objects_v2.return_value = {
            "Contents": [{"Key": "folder/file.txt"}],
        }

        result = backend.info("folder")

        assert result.name == "folder"
        assert result.type == "folder"
