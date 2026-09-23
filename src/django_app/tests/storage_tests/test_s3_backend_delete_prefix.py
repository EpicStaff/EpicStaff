from unittest.mock import patch

import pytest
from tables.services.storage_service.s3_backend import S3StorageBackend


def test_delete_prefix_refuses_an_empty_resolved_prefix():
    """A prefix-free backend must never resolve delete_prefix("") to the whole bucket."""
    with patch("tables.services.storage_service.s3_backend.boto3"):
        backend = S3StorageBackend(
            bucket_name="test-bucket",
            access_key="key",
            secret_key="secret",
            organization_prefix="",
        )
    with pytest.raises(ValueError):
        backend.delete_prefix("")


def test_delete_prefix_still_works_for_a_normal_org_prefix():
    """A real org prefix is unaffected by the empty-prefix guard."""
    with patch("tables.services.storage_service.s3_backend.boto3") as mock_boto3:
        backend = S3StorageBackend(
            bucket_name="test-bucket",
            access_key="key",
            secret_key="secret",
            organization_prefix="org_7/",
        )
        mock_client = mock_boto3.client.return_value
        mock_paginator = mock_client.get_paginator.return_value
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "org_7/a.txt"}]}]

        backend.delete_prefix("")

        mock_client.delete_objects.assert_called_once_with(
            Bucket="test-bucket", Delete={"Objects": [{"Key": "org_7/a.txt"}]}
        )
