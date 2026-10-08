"""
S3StorageBackend against a dict-backed fake S3 client: streamed uploads split
into exact parts and abort on failure, copies return the sizes the store reports
and leave nothing behind when they fail, cleanup deletes exactly the created keys
in batches, and storage outages surface as StorageUnreachable.
"""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

from tables.services.storage_service import s3_backend as s3_backend_module
from tables.services.storage_service.base import StorageUnreachable
from tables.services.storage_service.dataclasses import FileInfo
from tables.services.storage_service.s3_backend import S3StorageBackend
from tests.storage_tests.in_memory_backend import (
    MODIFIED,
    FakeS3Client,
    async_chunks,
    client_error,
    make_s3_backend,
)


@pytest.fixture
def client():
    return FakeS3Client()


@pytest.fixture
def backend(client):
    return make_s3_backend(client, part_size=8)


def _folder_source(client):
    client.objects.update(
        {
            "docs/": b"",
            "docs/a.txt": b"abc",
            "docs/b.txt": b"hello",
            "docs/sub/c.txt": b"0123456789",
        }
    )


class TestStreamedUpload:
    @pytest.mark.parametrize("chunks", [(b"abc", b"de"), ()], ids=["under-one-part", "empty"])
    @pytest.mark.asyncio
    async def test_a_body_under_one_part_is_a_single_put(self, backend, client, chunks):
        body = b"".join(chunks)

        assert await backend.upload_chunks("k", async_chunks(*chunks)) == len(body)
        assert client.puts == [body]
        assert client.completed is None

    @pytest.mark.asyncio
    async def test_parts_are_split_exactly_and_completed_in_order(self, backend, client):
        body = bytes(range(20))

        total = await backend.upload_chunks("k", async_chunks(body[:3], body[3:19], body[19:]))

        assert total == 20
        assert [part["PartNumber"] for part in client.completed] == [1, 2, 3]
        assert b"".join(client.parts[number] for number in (1, 2, 3)) == body
        assert [len(client.parts[number]) for number in (1, 2, 3)] == [8, 8, 4]
        assert client.peak_live_parts <= 1

    @pytest.mark.asyncio
    async def test_a_size_guard_stop_mid_multipart_aborts_the_upload(self, backend, client):
        def guard(total):
            if total > 10:
                raise ValueError("too big")

        with pytest.raises(ValueError):
            await backend.upload_chunks("k", async_chunks(b"x" * 9, b"x" * 9), size_guard=guard)
        assert client.aborted
        assert client.completed is None

    @pytest.mark.asyncio
    async def test_a_before_commit_failure_aborts_so_nothing_is_replaced(self, backend, client):
        async def reject(_total):
            raise ValueError("row rejected")

        with pytest.raises(ValueError):
            await backend.upload_chunks("k", async_chunks(b"x" * 20), before_commit=reject)
        assert client.aborted
        assert client.completed is None

        with pytest.raises(ValueError):
            await backend.upload_chunks("k", async_chunks(b"abc"), before_commit=reject)
        assert client.puts == []


class TestStorageOutages:
    @pytest.mark.parametrize(
        "error",
        [
            EndpointConnectionError(endpoint_url="http://storage:9000"),
            ReadTimeoutError(endpoint_url="http://storage:9000"),
            client_error("ServiceUnavailable", 503),
        ],
        ids=["unreachable", "read-timeout", "5xx"],
    )
    def test_an_outage_is_storage_unreachable(self, backend, client, monkeypatch, error):
        def _fail(**_kwargs):
            raise error

        monkeypatch.setattr(client, "put_object", _fail)

        with pytest.raises(StorageUnreachable) as caught:
            backend.put_bytes("k", b"x")
        assert caught.value.__cause__ is error

    def test_a_4xx_is_a_misconfiguration_not_an_outage(self, backend, client, monkeypatch):
        error = client_error("AccessDenied", 403)

        def _fail(**_kwargs):
            raise error

        monkeypatch.setattr(client, "put_object", _fail)

        with pytest.raises(ClientError) as caught:
            backend.put_bytes("k", b"x")
        assert caught.value is error


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
    """A folder name is taken by a folder or by a file of that name: some stores
    (e.g. MinIO) refuse keys under an object."""

    @pytest.mark.parametrize(
        ("existing", "expected"),
        [
            ({"report": b"keep me"}, "report (1)"),
            ({"report/old.txt": b"x", "report (1)": b"y"}, "report (2)"),
            ({"reports": b"x"}, "report"),
        ],
        ids=["same-name-file", "folder-and-file", "free"],
    )
    def test_unique_folder_key_skips_folders_and_files_of_that_name(
        self, backend, client, existing, expected
    ):
        client.objects.update(existing)

        assert backend.unique_key("report", is_folder=True) == expected

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

    def test_a_claim_under_a_same_name_file_is_a_lost_claim(self, backend, client, monkeypatch):
        def _refuse(**_kwargs):
            raise client_error("XMinioParentIsObject", 400)

        monkeypatch.setattr(client, "put_object", _refuse)

        assert backend.claim_folder("report") is False

    def test_another_4xx_on_claim_still_raises(self, backend, client, monkeypatch):
        def _refuse(**_kwargs):
            raise client_error("AccessDenied", 403)

        monkeypatch.setattr(client, "put_object", _refuse)

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
        client.copy_error = EndpointConnectionError(endpoint_url="http://storage:9000")

        with pytest.raises(EndpointConnectionError):
            backend.move("docs", "dest")

        assert client.objects == objects_before

    def test_a_failing_cleanup_does_not_replace_the_copy_error(self, backend, client):
        _folder_source(client)
        client.fail_copy_number = 3
        client.delete_error = client_error("InternalError", 500, "DeleteObjects")

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

        assert backend.head_file("out/report.txt") == FileInfo(
            id=None,
            name="report.txt",
            path="out/report.txt",
            size=5,
            content_type="text/plain",
            modified=MODIFIED.isoformat(),
        )

    def test_missing_file_is_none(self, backend):
        assert backend.head_file("ghost.txt") is None

    def test_a_storage_error_propagates(self, backend, client, monkeypatch):
        error = client_error("InternalError", 500, "HeadObject")

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
        S3StorageBackend(
            bucket_name="b", access_key="k", secret_key="s", organization_prefix="", part_size=8
        )

    main_config, head_file_config = (call.kwargs["config"] for call in make_client.call_args_list)
    assert (main_config.connect_timeout, main_config.read_timeout) == (10, 300)
    assert head_file_config.connect_timeout <= 5
    assert head_file_config.read_timeout <= 5
    assert head_file_config.retries == {"mode": "standard", "total_max_attempts": 1}
