"""
S3StorageBackend copy / delete_keys / head_file against a dict-backed fake S3
client: copies return the sizes the store reports, a copy failing midway leaves
no objects behind, and cleanup deletes exactly the created keys in batches.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from tables.services.storage_service import s3_backend as s3_backend_module
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.s3_backend import S3StorageBackend

_MODIFIED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, operation
    )


class _Paginator:
    def __init__(self, client, page_size):
        self._client = client
        self._page_size = page_size

    def paginate(self, *, Bucket, Prefix):
        keys = sorted(key for key in self._client.objects if key.startswith(Prefix))
        for start in range(0, len(keys), self._page_size):
            yield {
                "Contents": [
                    {
                        "Key": key,
                        "Size": len(self._client.objects[key]),
                        "LastModified": _MODIFIED,
                    }
                    for key in keys[start : start + self._page_size]
                ]
            }


class FakeS3Client:
    """The slice of the boto3 S3 client that copy and delete_keys use."""

    def __init__(self, page_size=2):
        self.objects: dict[str, bytes] = {}
        self.page_size = page_size
        self.fail_copy_number: int | None = None  # 1-based copy_object call to fail
        self.copy_error: BaseException = _client_error("InternalError", 500, "CopyObject")
        self.delete_error: BaseException | None = None
        self.delete_batches: list[list[str]] = []
        self.head_calls: list[str] = []
        self._copies = 0

    def head_object(self, *, Bucket, Key):
        self.head_calls.append(Key)
        if Key not in self.objects:
            raise _client_error("404", 404, "HeadObject")
        return {
            "ContentLength": len(self.objects[Key]),
            "LastModified": _MODIFIED,
            "ContentType": "text/plain",
        }

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys=1000, Delimiter=None):
        keys = sorted(key for key in self.objects if key.startswith(Prefix))[:MaxKeys]
        return {
            "KeyCount": len(keys),
            "Contents": [
                {"Key": key, "Size": len(self.objects[key]), "LastModified": _MODIFIED}
                for key in keys
            ],
        }

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self, self.page_size)

    def copy_object(self, *, CopySource, Bucket, Key):
        self._copies += 1
        if self._copies == self.fail_copy_number:
            raise self.copy_error
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_objects(self, *, Bucket, Delete):
        keys = [entry["Key"] for entry in Delete["Objects"]]
        assert len(keys) <= 1000
        self.delete_batches.append(keys)
        if self.delete_error is not None:
            raise self.delete_error
        for key in keys:
            self.objects.pop(key, None)
        return {}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.objects[Key] = bytes(Body)


def make_s3_backend(client: FakeS3Client) -> S3StorageBackend:
    backend = S3StorageBackend.__new__(S3StorageBackend)
    backend.bucket_name = "bucket"
    backend.organization_prefix = ""
    backend.client = client
    backend._head_file_client = client
    return backend


@pytest.fixture
def client():
    return FakeS3Client()


@pytest.fixture
def backend(client):
    return make_s3_backend(client)


def _folder_source(client):
    client.objects.update(
        {
            "docs/": b"",
            "docs/a.txt": b"abc",
            "docs/b.txt": b"hello",
            "docs/sub/c.txt": b"0123456789",
        }
    )


class TestCopySizes:
    def test_file_copy_returns_the_stored_size(self, backend, client):
        client.objects["a.txt"] = b"0123456789"
        client.objects["dest/a.txt"] = b"older"

        assert backend.copy("a.txt", "dest") == [("dest/a (1).txt", 10)]
        assert client.objects["dest/a (1).txt"] == b"0123456789"

    def test_folder_copy_returns_every_created_key_with_its_size(self, backend, client):
        _folder_source(client)

        copied = backend.copy("docs", "dest")

        assert sorted(copied) == [
            ("dest/docs/", 0),
            ("dest/docs/a.txt", 3),
            ("dest/docs/b.txt", 5),
            ("dest/docs/sub/c.txt", 10),
        ]

    def test_missing_source_raises_file_not_found(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.copy("ghost", "dest")


class TestFolderNaming:
    """A folder name is taken by a folder or by a file of that name: MinIO refuses
    keys under an object (XMinioParentIsObject)."""

    def test_a_file_of_the_same_name_takes_a_folder_name(self, backend, client):
        client.objects["report"] = b"keep me"

        assert backend.unique_key("report", is_folder=True) == "report (1)"

    def test_folder_and_file_names_are_both_skipped(self, backend, client):
        client.objects.update({"report/old.txt": b"x", "report (1)": b"y"})

        assert backend.unique_key("report", is_folder=True) == "report (2)"

    def test_a_free_name_is_kept(self, backend, client):
        client.objects["reports"] = b"x"

        assert backend.unique_key("report", is_folder=True) == "report"

    def test_a_folder_copied_next_to_a_same_name_file_gets_the_next_name(self, backend, client):
        _folder_source(client)
        client.objects["dest/docs"] = b"a file named like the folder"

        copied = backend.copy("docs", "dest")

        assert {key for key, _ in copied} == {
            "dest/docs (1)/",
            "dest/docs (1)/a.txt",
            "dest/docs (1)/b.txt",
            "dest/docs (1)/sub/c.txt",
        }
        assert client.objects["dest/docs"] == b"a file named like the folder"

    def test_a_claim_under_a_same_name_file_is_a_lost_claim(self, backend, client):
        def put_object(*, Bucket, Key, Body, **_kwargs):
            raise _client_error("XMinioParentIsObject", 400, "PutObject")

        client.put_object = put_object

        assert backend.claim_folder("report") is False

    def test_another_4xx_on_claim_still_raises(self, backend, client):
        def put_object(*, Bucket, Key, Body, **_kwargs):
            raise _client_error("AccessDenied", 403, "PutObject")

        client.put_object = put_object

        with pytest.raises(ClientError):
            backend.claim_folder("report")


class TestCopyFailureCleanup:
    @pytest.mark.parametrize("failing_copy", [1, 3, 4])
    def test_a_failed_copy_leaves_no_created_object(self, backend, client, failing_copy):
        _folder_source(client)
        client.objects["dest/other.txt"] = b"written by someone else"
        objects_before = dict(client.objects)
        client.fail_copy_number = failing_copy

        with pytest.raises(ClientError) as caught:
            backend.copy("docs", "dest")

        assert caught.value is client.copy_error
        assert client.objects == objects_before

    def test_a_failed_move_leaves_the_source_and_no_copies(self, backend, client):
        _folder_source(client)
        objects_before = dict(client.objects)
        client.fail_copy_number = 2
        client.copy_error = EndpointConnectionError(endpoint_url="http://minio:9000")

        with pytest.raises(EndpointConnectionError):
            backend.move("docs", "dest")

        assert client.objects == objects_before

    def test_a_failing_cleanup_does_not_replace_the_copy_error(self, backend, client):
        _folder_source(client)
        client.fail_copy_number = 3
        client.delete_error = _client_error("InternalError", 500, "DeleteObjects")

        with pytest.raises(ClientError) as caught:
            backend.copy("docs", "dest")

        assert caught.value is client.copy_error
        assert client.delete_batches == [["dest/docs/", "dest/docs/a.txt"]]


class TestDeleteKeys:
    def test_deletes_exactly_the_given_keys_in_batches_of_1000(self, backend, client):
        keys = [f"dest/f{index}.txt" for index in range(2500)]
        client.objects.update({key: b"x" for key in keys})
        client.objects["dest/kept.txt"] = b"not ours"

        backend.delete_keys(keys)

        assert [len(batch) for batch in client.delete_batches] == [1000, 1000, 500]
        assert client.objects == {"dest/kept.txt": b"not ours"}

    def test_per_key_errors_in_the_response_raise(self, backend, client, monkeypatch):
        monkeypatch.setattr(
            client,
            "delete_objects",
            lambda **_kwargs: {"Errors": [{"Key": "dest/a.txt", "Code": "AccessDenied"}]},
        )

        with pytest.raises(RuntimeError, match="dest/a.txt"):
            backend.delete_keys(["dest/a.txt"])


class TestHeadFile:
    def test_returns_the_stored_metadata(self, backend, client):
        client.objects["out/report.txt"] = b"12345"

        info = backend.head_file("out/report.txt")

        assert info == FileInfo(
            id=None,
            name="report.txt",
            path="out/report.txt",
            size=5,
            content_type="text/plain",
            modified=_MODIFIED.isoformat(),
        )

    def test_missing_file_is_none(self, backend):
        assert backend.head_file("ghost.txt") is None

    def test_a_storage_error_propagates(self, backend, client, monkeypatch):
        error = _client_error("InternalError", 500, "HeadObject")

        def _fail(**_kwargs):
            raise error

        monkeypatch.setattr(client, "head_object", _fail)

        with pytest.raises(ClientError) as caught:
            backend.head_file("a.txt")
        assert caught.value is error

    def test_uses_its_own_short_no_retry_client(self, backend, client):
        quick_client = FakeS3Client()
        quick_client.objects["a.txt"] = b"abc"
        backend._head_file_client = quick_client

        assert backend.head_file("a.txt").size == 3
        assert quick_client.head_calls == ["a.txt"]
        assert client.head_calls == []


def test_head_file_client_is_short_and_not_retried_while_the_main_client_is_unchanged():
    with patch.object(s3_backend_module.boto3, "client") as make_client:
        S3StorageBackend(bucket_name="b", access_key="k", secret_key="s", organization_prefix="")

    main_config, head_file_config = (call.kwargs["config"] for call in make_client.call_args_list)
    assert (main_config.connect_timeout, main_config.read_timeout) == (10, 300)
    assert head_file_config.connect_timeout <= 5
    assert head_file_config.read_timeout <= 5
    assert head_file_config.retries == {"mode": "standard", "total_max_attempts": 1}
