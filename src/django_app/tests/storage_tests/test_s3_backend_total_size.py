"""S3StorageBackend.total_size counts every byte stored under a prefix.

Every listed object counts, folder markers included (a marker can hold content), on every
page of the listing; so do the parts of multipart uploads that were never completed, which
the store keeps but never lists as objects. Only the organization's prefix is listed.

A real boto3 client with botocore's Stubber: each request is checked against the S3 service
model, so a wrong operation name or parameter fails here rather than against the live store.

InMemoryStorageBackend stands in for S3StorageBackend in the measurement tests, so its
`total_size` is pinned to the same contract on the same store contents. It has no paging and
no multipart uploads, so those cases are S3-only.
"""

import boto3
import pytest
from botocore.stub import Stubber

from tests.storage_tests.in_memory_backend import MODIFIED, InMemoryStorageBackend, make_s3_backend

BUCKET = "bucket"
ORG_PREFIX = "org_7/"


@pytest.fixture
def s3_client():
    return boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="http://storage.invalid",
    )


@pytest.fixture
def stubbed(s3_client):
    with Stubber(s3_client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def backend(s3_client):
    backend = make_s3_backend(s3_client)
    backend.bucket_name = BUCKET
    backend.organization_prefix = ORG_PREFIX
    return backend


def _object(key: str, size: int) -> dict:
    return {"Key": key, "Size": size, "LastModified": MODIFIED}


def _no_uploads(stubbed, prefix: str) -> None:
    stubbed.add_response(
        "list_multipart_uploads",
        {"Bucket": BUCKET, "IsTruncated": False, "Uploads": []},
        {"Bucket": BUCKET, "Prefix": prefix},
    )


def test_objects_on_every_page_and_markers_with_content_count(stubbed, backend):
    stubbed.add_response(
        "list_objects_v2",
        {
            "IsTruncated": True,
            "NextContinuationToken": "page-2",
            "Contents": [_object("org_7/", 0), _object("org_7/a.txt", 10)],
        },
        {"Bucket": BUCKET, "Prefix": ORG_PREFIX},
    )
    stubbed.add_response(
        "list_objects_v2",
        {
            "IsTruncated": False,
            "Contents": [_object("org_7/docs/", 3), _object("org_7/docs/b.bin", 100)],
        },
        {"Bucket": BUCKET, "Prefix": ORG_PREFIX, "ContinuationToken": "page-2"},
    )
    _no_uploads(stubbed, ORG_PREFIX)

    assert backend.total_size("") == 113


def test_parts_of_unfinished_multipart_uploads_count(stubbed, backend):
    stubbed.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "Contents": [_object("org_7/done.bin", 20)]},
        {"Bucket": BUCKET, "Prefix": ORG_PREFIX},
    )
    stubbed.add_response(
        "list_multipart_uploads",
        {
            "Bucket": BUCKET,
            "IsTruncated": False,
            "Uploads": [
                {"Key": "org_7/big.bin", "UploadId": "upload-1"},
                {"Key": "org_7/huge.bin", "UploadId": "upload-2"},
            ],
        },
        {"Bucket": BUCKET, "Prefix": ORG_PREFIX},
    )
    stubbed.add_response(
        "list_parts",
        {
            "Bucket": BUCKET,
            "Key": "org_7/big.bin",
            "UploadId": "upload-1",
            "IsTruncated": False,
            "Parts": [{"PartNumber": 1, "Size": 5}, {"PartNumber": 2, "Size": 7}],
        },
        {"Bucket": BUCKET, "Key": "org_7/big.bin", "UploadId": "upload-1"},
    )
    stubbed.add_response(
        "list_parts",
        {"Bucket": BUCKET, "Key": "org_7/huge.bin", "UploadId": "upload-2", "IsTruncated": False},
        {"Bucket": BUCKET, "Key": "org_7/huge.bin", "UploadId": "upload-2"},
    )

    assert backend.total_size("") == 32


def test_an_empty_prefix_stores_nothing(stubbed, backend):
    stubbed.add_response(
        "list_objects_v2", {"IsTruncated": False, "KeyCount": 0}, {"Bucket": BUCKET, "Prefix": ORG_PREFIX}
    )
    _no_uploads(stubbed, ORG_PREFIX)

    assert backend.total_size("") == 0


def test_a_folder_is_measured_under_the_organization_prefix(stubbed, backend):
    stubbed.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "Contents": [_object("org_7/docs/b.bin", 100)]},
        {"Bucket": BUCKET, "Prefix": "org_7/docs/"},
    )
    _no_uploads(stubbed, "org_7/docs/")

    assert backend.total_size("docs") == 100


@pytest.mark.parametrize(
    ("stored", "prefix", "expected"),
    [
        pytest.param(
            {
                "org_7/": 0,
                "org_7/a.txt": 10,
                "org_7/docs/": 3,
                "org_7/docs/b.bin": 100,
                "org_70/other.bin": 1000,
                "org_8/other.bin": 1000,
            },
            "",
            113,
            id="every-object-and-marker-under-the-organization-only",
        ),
        pytest.param({}, "", 0, id="empty-prefix"),
        pytest.param(
            {"org_7/a.txt": 10, "org_7/docs/b.bin": 100, "org_7/docsx/c.bin": 1000},
            "docs",
            100,
            id="folder-under-the-organization-prefix",
        ),
    ],
)
def test_the_in_memory_fake_measures_like_s3(stored, prefix, expected):
    fake = InMemoryStorageBackend(organization_prefix=ORG_PREFIX)
    fake._objects.update({key: (b"x" * size, MODIFIED) for key, size in stored.items()})

    assert fake.total_size(prefix) == expected
