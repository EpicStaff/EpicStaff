from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from tables.services.storage_service.s3_backend import S3StorageBackend


def _make_s3_backend() -> S3StorageBackend:
    with patch("tables.services.storage_service.s3_backend.boto3"):
        return S3StorageBackend(
            bucket_name="test",
            access_key="k",
            secret_key="s",
            organization_prefix="",
            endpoint_url=None,
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
