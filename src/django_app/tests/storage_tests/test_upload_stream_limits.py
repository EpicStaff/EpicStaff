"""Time limits and the early size checks of the streaming upload service. The
admission gate itself is covered by test_upload_admission, and its 429/503
rendering by test_upload_stream_endpoint."""

import asyncio
import contextlib
import tempfile
import threading

import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from django.test import override_settings

from tables.exceptions import (
    StorageQuotaExceeded,
    UploadDurationExceeded,
    UploadIdleTimeout,
    UploadTooLarge,
)
from tables.models import StorageFile
from tables.services.storage_service.upload import admission, archive_upload, file_upload, guards
from tests.storage_tests.in_memory_backend import (
    FakeS3Client,
    InMemoryStorageBackend,
    async_chunks,
    make_s3_backend,
    zip_bytes,
)


async def _stalls_after(*chunks):
    """A client that sends `chunks`, then goes silent without closing."""
    for chunk in chunks:
        yield chunk
    await asyncio.Event().wait()


async def _trickles(chunk: bytes, every: float):
    """A client that keeps sending, just slowly and forever."""
    while True:
        yield chunk
        await asyncio.sleep(every)


# --- idle timeout / max duration ------------------------------------------------


@pytest.mark.asyncio
@override_settings(UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_time_limits_reset_the_idle_timer_on_every_chunk():
    # 5 x 0.03 s is well past the 0.05 s idle timeout in total, but no single gap is
    async def _steady():
        for _ in range(5):
            await asyncio.sleep(0.03)
            yield b"x"

    assert len([chunk async for chunk in guards.within_time_limits(_steady())]) == 5


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_a_silent_client_aborts_the_multipart_upload_and_writes_no_row(org):
    client = FakeS3Client()

    with pytest.raises(UploadIdleTimeout, match="No data arrived") as caught:
        await file_upload.upload_file(
            org.id,
            "",
            "a.bin",
            _stalls_after(b"12345678"),
            None,
            backend=make_s3_backend(client, part_size=4),
        )

    assert caught.value.status_code == 408
    assert client.parts  # the multipart upload had really started
    assert client.aborted
    assert client.completed is None
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=10, UPLOAD_MAX_DURATION=0.1)
async def test_an_upload_past_the_max_duration_is_aborted_even_while_data_flows(org):
    client = FakeS3Client()

    with pytest.raises(UploadDurationExceeded, match="did not finish within") as caught:
        await file_upload.upload_file(
            org.id,
            "",
            "a.bin",
            _trickles(b"12345678", every=0.01),
            None,
            backend=make_s3_backend(client, part_size=4),
        )

    assert caught.value.status_code == 408
    assert client.aborted
    assert client.completed is None
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=0.2, UPLOAD_MAX_DURATION=60)
async def test_time_spent_sending_parts_to_storage_is_not_client_idle_time(org):
    # only the wait for the next body chunk counts; a slow storage PUT must not trip it
    class _SlowStorage(InMemoryStorageBackend):
        async def upload_chunks(self, path, chunks, **kwargs):
            async def _slow(source):
                async for chunk in source:
                    await asyncio.sleep(0.3)  # longer than the idle timeout
                    yield chunk

            return await super().upload_chunks(path, _slow(chunks), **kwargs)

    result = await file_upload.upload_file(
        org.id, "", "a.txt", async_chunks(b"ab", b"cd"), 4, backend=_SlowStorage()
    )

    assert result == {"path": "a.txt", "size": 4}


# --- declared size, checked before an upload slot ---------------------------------


class _AdmissionSpy:
    """Stands in for the upload gate: records every upload let in and whether the
    DB connection was still held at that moment."""

    def __init__(self):
        self.admitted: list[int] = []
        self.connection_open_at_admission: list[bool] = []

    @contextlib.asynccontextmanager
    async def admit(self, org_id: int):
        self.admitted.append(org_id)
        self.connection_open_at_admission.append(
            await sync_to_async(lambda: connection.connection is not None)()
        )
        yield


@pytest.fixture
def admission_spy(monkeypatch):
    spy = _AdmissionSpy()
    monkeypatch.setattr(admission, "_admission", spy)
    return spy


class _BodyWatch:
    """A request body that records whether anything read it."""

    def __init__(self, *chunks: bytes):
        self._chunks = chunks
        self.read = False

    async def __aiter__(self):
        self.read = True
        for chunk in self._chunks:
            yield chunk


_FILE_AND_ARCHIVE = pytest.mark.parametrize(
    ("upload", "filename"),
    [(file_upload.upload_file, "big.bin"), (archive_upload.upload_archive, "bundle.zip")],
    ids=["file", "archive"],
)


@pytest.mark.asyncio
@override_settings(
    MAX_STREAM_UPLOAD_FILE_SIZE=10, MAX_ARCHIVE_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9
)
@_FILE_AND_ARCHIVE
async def test_a_body_declared_over_its_size_limit_is_rejected_before_it_waits_for_a_slot(
    admission_spy, fake_backend, upload, filename
):
    body = _BodyWatch(b"x" * 11)

    with pytest.raises(UploadTooLarge):
        await upload(1, "", filename, body, 11, backend=fake_backend)

    assert admission_spy.admitted == []
    assert not body.read
    assert not fake_backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    MAX_STREAM_UPLOAD_FILE_SIZE=10, MAX_ARCHIVE_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9
)
@_FILE_AND_ARCHIVE
async def test_a_body_whose_content_length_lies_is_still_stopped_while_read(
    admission_spy, fake_backend, org, upload, filename
):
    with pytest.raises(UploadTooLarge):
        await upload(
            org.id, "", filename, async_chunks(b"x" * 6, b"x" * 6), 5, backend=fake_backend
        )

    assert admission_spy.admitted == [org.id]  # the declared size passed the early check
    assert not fake_backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    MAX_STREAM_UPLOAD_FILE_SIZE=None, MAX_ARCHIVE_FILE_SIZE=10**6, ORG_STORAGE_QUOTA=10**9
)
@pytest.mark.parametrize(
    ("upload", "filename", "body"),
    [
        (file_upload.upload_file, "a.txt", b"x" * 10),
        (archive_upload.upload_archive, "bundle.zip", zip_bytes({"a.txt": b"hello"})),
    ],
    ids=["file", "archive"],
)
async def test_an_upload_is_admitted_without_holding_a_db_connection(
    admission_spy, fake_backend, org, upload, filename, body
):
    # What the upload stream view does after the auth query; from here to the slot the
    # service must not open a connection that the (possibly long) wait would hold.
    await sync_to_async(lambda: connection.close())()

    await upload(org.id, "", filename, async_chunks(body), len(body), backend=fake_backend)

    assert admission_spy.admitted == [org.id]
    assert admission_spy.connection_open_at_admission == [False]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=None, ORG_STORAGE_QUOTA=10)
async def test_a_file_declared_over_the_free_space_waits_for_a_slot_then_is_rejected_unread(
    admission_spy, fake_backend, org
):
    # The quota is a DB query, so it is checked only once admitted; still before any
    # of the body is read.
    await StorageFile.objects.acreate(
        org=org, path="old.txt", name="old.txt", item_type="file", size=4
    )
    body = _BodyWatch(b"x" * 7)

    with pytest.raises(StorageQuotaExceeded):
        await file_upload.upload_file(org.id, "", "new.txt", body, 7, backend=fake_backend)  # 7 > 10 - 4

    assert admission_spy.admitted == [org.id]
    assert not body.read
    assert not fake_backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_archive_declared_over_the_free_space_is_still_admitted(
    admission_spy, fake_backend, org
):
    # only the unpacked size counts against the quota, and it is unknown up front
    archive = zip_bytes({"a.txt": b"hello"})

    with override_settings(ORG_STORAGE_QUOTA=len(archive) - 1, MAX_ARCHIVE_FILE_SIZE=10**6):
        result = await archive_upload.upload_archive(
            org.id, "", "bundle.zip", async_chunks(archive), len(archive), backend=fake_backend
        )

    assert result["extracted"] == ["bundle/a.txt"]
    assert admission_spy.admitted == [org.id]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_the_archive_is_buffered_off_the_event_loop(monkeypatch, fake_backend, org):
    # past max_size a SpooledTemporaryFile write spills to disk: never on the loop
    loop_thread = threading.get_ident()
    write_threads = []

    class _Recording(tempfile.SpooledTemporaryFile):
        def write(self, data):
            write_threads.append(threading.get_ident())
            return super().write(data)

    monkeypatch.setattr(archive_upload.tempfile, "SpooledTemporaryFile", _Recording)
    archive = zip_bytes({"a.txt": b"hello"})

    await archive_upload.upload_archive(
        org.id,
        "",
        "bundle.zip",
        async_chunks(archive[:20], archive[20:]),
        None,
        backend=fake_backend,
    )

    assert len(write_threads) == 2
    assert loop_thread not in write_threads
