import threading

import pytest

from tables.services.storage_service.s3_backend import S3StorageBackend


class _FakeS3Client:
    def __init__(self):
        self.puts: list[bytes] = []
        self.parts: dict[int, bytes] = {}
        self.completed: list[dict] | None = None
        self.aborted = False
        self._live = 0
        self.peak_live = 0
        self._lock = threading.Lock()

    def put_object(self, *, Bucket, Key, Body):
        self.puts.append(Body)

    def create_multipart_upload(self, *, Bucket, Key):
        return {"UploadId": "u1"}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        with self._lock:
            self._live += 1
            self.peak_live = max(self.peak_live, self._live)
        self.parts[PartNumber] = Body
        with self._lock:
            self._live -= 1
        return {"ETag": f"e{PartNumber}"}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        self.completed = MultipartUpload["Parts"]

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.aborted = True


def _backend() -> tuple[S3StorageBackend, _FakeS3Client]:
    backend = S3StorageBackend.__new__(S3StorageBackend)
    backend.bucket_name = "b"
    backend.organization_prefix = ""
    backend.client = _FakeS3Client()
    return backend, backend.client


async def _aiter(*chunks):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_body_under_one_part_is_a_single_put():
    backend, client = _backend()
    assert await backend.upload_chunks("k", _aiter(b"abc", b"de"), part_size=8) == 5
    assert client.puts == [b"abcde"]
    assert client.completed is None


@pytest.mark.asyncio
async def test_empty_body_is_a_single_empty_put():
    backend, client = _backend()
    assert await backend.upload_chunks("k", _aiter(), part_size=8) == 0
    assert client.puts == [b""]


@pytest.mark.asyncio
async def test_parts_are_split_exactly_and_completed_in_order():
    backend, client = _backend()
    body = bytes(range(20))
    total = await backend.upload_chunks("k", _aiter(body[:3], body[3:19], body[19:]), part_size=8)

    assert total == 20
    assert [p["PartNumber"] for p in client.completed] == [1, 2, 3]
    assert b"".join(client.parts[n] for n in (1, 2, 3)) == body
    assert [len(client.parts[n]) for n in (1, 2, 3)] == [8, 8, 4]
    assert client.peak_live <= 1


@pytest.mark.asyncio
async def test_guard_abort_mid_multipart_aborts_the_upload():
    backend, client = _backend()

    def guard(total):
        if total > 10:
            raise ValueError("too big")

    with pytest.raises(ValueError):
        await backend.upload_chunks("k", _aiter(b"x" * 9, b"x" * 9), part_size=8, size_guard=guard)
    assert client.aborted
    assert client.completed is None


@pytest.mark.asyncio
async def test_before_commit_failure_aborts_so_nothing_is_replaced():
    backend, client = _backend()

    async def reject(_total):
        raise ValueError("row rejected")

    with pytest.raises(ValueError):
        await backend.upload_chunks("k", _aiter(b"x" * 20), part_size=8, before_commit=reject)
    assert client.aborted
    assert client.completed is None

    with pytest.raises(ValueError):
        await backend.upload_chunks("k", _aiter(b"abc"), part_size=8, before_commit=reject)
    assert client.puts == []
