"""Transfer archives in storage: where they are kept, how they are read back, and
how a job's archives are removed. The S3 read is checked against a stubbed client."""

import io
import uuid

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from tables.services.storage_service.s3_backend import S3StorageBackend
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tests.storage_backend_fake import FakeStorageBackend


@pytest.fixture
def backend():
    return FakeStorageBackend()


@pytest.fixture
def store(backend):
    return TransferArchiveStore(backend=backend)


def test_archives_are_kept_under_system_transfers_per_job(store, backend):
    job_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    key = store.upload_file(job_id, "export.zip", io.BytesIO(b"zip bytes"))

    assert key == "system/transfers/12345678-1234-5678-1234-567812345678/export.zip"
    assert backend.objects == {key: b"zip bytes"}


def test_an_archive_is_read_back_whole_in_bounded_chunks(store, backend):
    data = bytes(range(256)) * 10
    key = store.upload_file(uuid.uuid4(), "export.zip", io.BytesIO(data))

    chunks = list(store.iter_chunks(key, chunk_size=1000))
    destination = io.BytesIO()
    store.download_to(key, destination)

    assert b"".join(chunks) == data
    assert [len(chunk) for chunk in chunks] == [1000, 1000, 560]
    assert destination.getvalue() == data


def test_deleting_a_job_removes_only_its_archives(store, backend):
    removed_job, kept_job = uuid.uuid4(), uuid.uuid4()
    store.upload_file(removed_job, "import.zip", io.BytesIO(b"a"))
    store.upload_file(removed_job, "export.zip", io.BytesIO(b"b"))
    kept_key = store.upload_file(kept_job, "export.zip", io.BytesIO(b"c"))

    store.delete_job(removed_job)
    store.delete_job(uuid.uuid4())  # nothing stored: not an error

    assert list(backend.objects) == [kept_key]


# --- the S3 read the store relies on -------------------------------------------------------


@pytest.fixture
def s3_backend(settings):
    backend = S3StorageBackend(
        bucket_name="bucket",
        access_key="access",
        secret_key="secret",
        organization_prefix="",
        endpoint_url="http://storage.invalid",
        part_size=5 * 1024 * 1024,
    )
    with Stubber(backend.client) as stubber:
        yield backend, stubber


def test_s3_object_is_streamed_in_chunks(s3_backend):
    backend, stubber = s3_backend
    data = b"x" * 2500
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(data), len(data))},
        {"Bucket": "bucket", "Key": "system/transfers/job/export.zip"},
    )

    chunks = list(backend.iter_object("system/transfers/job/export.zip", 1000))

    assert [len(chunk) for chunk in chunks] == [1000, 1000, 500]
    assert b"".join(chunks) == data


def test_a_missing_s3_object_is_file_not_found(s3_backend):
    backend, stubber = s3_backend
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    with pytest.raises(FileNotFoundError):
        list(backend.iter_object("system/transfers/job/export.zip", 1000))
