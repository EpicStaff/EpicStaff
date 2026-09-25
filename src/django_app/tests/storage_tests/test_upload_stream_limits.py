import asyncio
import contextlib
import io
import tempfile
import threading
import zipfile

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from asgiref.sync import sync_to_async
from django.db import connection
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from tables.exceptions import (
    OrgUploadLimitReached,
    StorageQuotaExceeded,
    StorageUnavailable,
    UploadDurationExceeded,
    UploadIdleTimeout,
    UploadTooLarge,
)
from tables.models import Organization, StorageFile
from tables.services.storage_service import upload_stream_service as svc
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from tests.storage_tests.test_s3_stream_upload import _backend as _fake_s3_backend


async def _aiter(*chunks):
    for chunk in chunks:
        yield chunk


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


class _ClientGone(Exception):
    pass


async def _disconnects_after(*chunks):
    for chunk in chunks:
        yield chunk
    raise _ClientGone()


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _client_error(http_status: int, code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": http_status}},
        "UploadPart",
    )


class _FailingBackend:
    def __init__(self, error: Exception):
        self._error = error

    async def upload_chunks(self, path, chunks, **_kwargs):
        async for _ in chunks:
            raise self._error
        raise self._error


# --- idle timeout / max duration ------------------------------------------------


async def _drain(chunks) -> list[bytes]:
    return [chunk async for chunk in chunks]


@pytest.mark.asyncio
@override_settings(UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_time_limits_pass_a_prompt_body_through_unchanged():
    assert await _drain(svc._within_time_limits(_aiter(b"a", b"b", b"c"))) == [b"a", b"b", b"c"]


@pytest.mark.asyncio
@override_settings(UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_time_limits_stop_a_client_that_goes_silent():
    received = []
    with pytest.raises(UploadIdleTimeout) as caught:
        async for chunk in svc._within_time_limits(_stalls_after(b"a")):
            received.append(chunk)
    assert received == [b"a"]
    assert caught.value.status_code == 408


@pytest.mark.asyncio
@override_settings(UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_time_limits_reset_the_idle_timer_on_every_chunk():
    # 5 x 0.03 s is well past the 0.05 s idle timeout in total, but no single gap is
    async def _steady():
        for _ in range(5):
            await asyncio.sleep(0.03)
            yield b"x"

    assert len(await _drain(svc._within_time_limits(_steady()))) == 5


@pytest.mark.asyncio
@override_settings(UPLOAD_IDLE_TIMEOUT=10, UPLOAD_MAX_DURATION=0.1)
async def test_time_limits_stop_a_steady_upload_at_the_max_duration():
    with pytest.raises(UploadDurationExceeded) as caught:
        await _drain(svc._within_time_limits(_trickles(b"x", every=0.01)))
    assert caught.value.status_code == 408


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    ORG_STORAGE_QUOTA=10**9, UPLOAD_PART_SIZE=4, UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60
)
async def test_a_silent_client_aborts_the_multipart_upload_and_writes_no_row():
    org = await Organization.objects.acreate(name="Acme")
    backend, client = _fake_s3_backend()

    with pytest.raises(UploadIdleTimeout, match="No data arrived"):
        await svc.upload_file(org.id, "", "a.bin", _stalls_after(b"12345678"), None, backend=backend)

    assert client.parts  # the multipart upload had really started
    assert client.aborted
    assert client.completed is None
    assert not await StorageFile.objects.filter(org=org).aexists()
    assert svc._upload_admission().uploads_of(org.id) == 0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    ORG_STORAGE_QUOTA=10**9, UPLOAD_PART_SIZE=4, UPLOAD_IDLE_TIMEOUT=10, UPLOAD_MAX_DURATION=0.1
)
async def test_an_upload_past_the_max_duration_is_aborted_even_while_data_flows():
    org = await Organization.objects.acreate(name="Acme")
    backend, client = _fake_s3_backend()

    with pytest.raises(UploadDurationExceeded, match="did not finish within"):
        await svc.upload_file(
            org.id, "", "a.bin", _trickles(b"12345678", every=0.01), None, backend=backend
        )

    assert client.aborted
    assert client.completed is None
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=0.05, UPLOAD_MAX_DURATION=60)
async def test_a_silent_client_aborts_an_archive_upload_before_anything_is_stored():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"a.txt": b"hello"})

    with pytest.raises(UploadIdleTimeout):
        await svc.upload_archive(
            org.id, "", "bundle.zip", _stalls_after(archive[:10]), None, backend=backend
        )

    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_IDLE_TIMEOUT=0.2, UPLOAD_MAX_DURATION=60)
async def test_time_spent_sending_parts_to_storage_is_not_client_idle_time():
    # only the wait for the next body chunk counts; a slow MinIO PUT must not trip it
    org = await Organization.objects.acreate(name="Acme")

    class _SlowStorage(InMemoryStorageBackend):
        async def upload_chunks(self, path, chunks, **kwargs):
            async def _slow(source):
                async for chunk in source:
                    await asyncio.sleep(0.3)  # longer than the idle timeout
                    yield chunk

            return await super().upload_chunks(path, _slow(chunks), **kwargs)

    backend = _SlowStorage(organization_prefix="")
    result = await svc.upload_file(org.id, "", "a.txt", _aiter(b"ab", b"cd"), 4, backend=backend)

    assert result == {"path": "a.txt", "size": 4}


# --- per-org limit ----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, UPLOAD_MAX_CONCURRENCY=4, UPLOAD_MAX_CONCURRENCY_PER_ORG=1)
async def test_one_org_cannot_start_more_uploads_than_its_share():
    acme = await Organization.objects.acreate(name="Acme")
    beta = await Organization.objects.acreate(name="Beta")
    backend = InMemoryStorageBackend(organization_prefix="")
    release = asyncio.Event()

    async def _held_open():
        yield b"x"
        await release.wait()

    first = asyncio.create_task(
        svc.upload_file(acme.id, "", "first.txt", _held_open(), None, backend=backend)
    )
    await asyncio.sleep(0.05)

    with pytest.raises(OrgUploadLimitReached):
        await svc.upload_file(acme.id, "", "second.txt", _aiter(b"y"), 1, backend=backend)
    other_org = await svc.upload_file(beta.id, "", "b.txt", _aiter(b"z"), 1, backend=backend)

    release.set()
    await first
    assert other_org["path"] == "b.txt"
    assert svc._upload_admission().uploads_of(acme.id) == 0
    assert not await StorageFile.objects.filter(org=acme, path="second.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5, UPLOAD_MAX_CONCURRENCY_PER_ORG=1)
@pytest.mark.parametrize(
    ("chunks", "expected_error"),
    [
        (lambda: _aiter(b"ok"), None),
        (lambda: _aiter(b"x" * 10), StorageQuotaExceeded),
        (lambda: _disconnects_after(b"x"), _ClientGone),
    ],
    ids=["success", "error", "disconnect"],
)
async def test_the_org_share_is_given_back_after_every_outcome(chunks, expected_error):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    if expected_error is None:
        await svc.upload_file(org.id, "", "a.txt", chunks(), None, backend=backend)
    else:
        with pytest.raises(expected_error):
            await svc.upload_file(org.id, "", "a.txt", chunks(), None, backend=backend)

    assert svc._upload_admission().uploads_of(org.id) == 0
    # the single allowed upload is free again
    await svc.upload_file(org.id, "", "b.txt", _aiter(b"ok"), 2, backend=backend)


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
    monkeypatch.setattr(svc, "_upload_admission", lambda: spy)
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


@pytest.mark.asyncio
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9)
async def test_a_file_declared_over_the_size_limit_is_rejected_before_it_waits_for_a_slot(
    admission_spy,
):
    body = _BodyWatch(b"x" * 11)
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(UploadTooLarge):
        await svc.upload_file(1, "", "big.bin", body, 11, backend=backend)

    assert admission_spy.admitted == []
    assert not body.read
    assert not backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=None, ORG_STORAGE_QUOTA=10)
async def test_a_file_declared_over_the_free_space_waits_for_a_slot_then_is_rejected_unread(
    admission_spy,
):
    # The quota is a DB query, so it is checked only once admitted; still before any
    # of the body is read.
    org = await Organization.objects.acreate(name="Acme")
    await StorageFile.objects.acreate(org=org, path="old.txt", name="old.txt", item_type="file", size=4)
    body = _BodyWatch(b"x" * 7)
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(StorageQuotaExceeded):
        await svc.upload_file(org.id, "", "new.txt", body, 7, backend=backend)  # 7 > 10 - 4

    assert admission_spy.admitted == [org.id]
    assert not body.read
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org, path="new.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=None, ORG_STORAGE_QUOTA=10)
async def test_the_quota_check_counts_the_file_being_overwritten_as_freed(admission_spy):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.upload_file(org.id, "", "a.txt", _aiter(b"x" * 8), 8, backend=backend)

    result = await svc.upload_file(org.id, "", "a.txt", _aiter(b"y" * 9), 9, backend=backend)

    assert result == {"path": "a.txt", "size": 9}
    assert admission_spy.admitted == [org.id, org.id]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=10, ORG_STORAGE_QUOTA=10)
async def test_a_file_declared_within_the_limits_is_admitted_without_holding_a_db_connection(
    admission_spy,
):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    # What asgi_upload does after the auth query; from here to the slot the
    # service must not open a connection that the (possibly long) wait would hold.
    await sync_to_async(lambda: connection.close())()

    result = await svc.upload_file(org.id, "", "a.txt", _aiter(b"x" * 10), 10, backend=backend)

    assert result == {"path": "a.txt", "size": 10}
    assert admission_spy.admitted == [org.id]
    assert admission_spy.connection_open_at_admission == [False]
    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 10


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    MAX_STREAM_UPLOAD_FILE_SIZE=10,
    ORG_STORAGE_QUOTA=10**9,
    UPLOAD_MAX_CONCURRENCY=4,
    UPLOAD_MAX_CONCURRENCY_PER_ORG=1,
)
async def test_an_oversize_file_gets_413_even_while_the_org_has_no_free_slot():
    # without the early reject this would be a 429, and the client would retry it
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    release = asyncio.Event()

    async def _held_open():
        yield b"x"
        await release.wait()

    first = asyncio.create_task(
        svc.upload_file(org.id, "", "first.txt", _held_open(), None, backend=backend)
    )
    await asyncio.sleep(0.05)

    with pytest.raises(UploadTooLarge):
        await svc.upload_file(org.id, "", "big.bin", _aiter(b"x" * 11), 11, backend=backend)
    with pytest.raises(OrgUploadLimitReached):
        await svc.upload_file(org.id, "", "small.bin", _aiter(b"x"), 1, backend=backend)

    release.set()
    await first


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_STREAM_UPLOAD_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9)
async def test_a_file_whose_content_length_lies_is_still_stopped_mid_stream(admission_spy):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(UploadTooLarge):
        await svc.upload_file(
            org.id, "", "a.bin", _aiter(b"x" * 6, b"x" * 6), 5, backend=backend
        )

    assert admission_spy.admitted == [org.id]  # the declared size passed the early check
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@override_settings(MAX_ARCHIVE_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9)
async def test_an_archive_declared_over_the_archive_limit_is_rejected_before_it_waits_for_a_slot(
    admission_spy,
):
    body = _BodyWatch(b"x" * 11)
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(UploadTooLarge):
        await svc.upload_archive(1, "", "bundle.zip", body, 11, backend=backend)

    assert admission_spy.admitted == []
    assert not body.read
    assert not backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_ARCHIVE_FILE_SIZE=10**6, ORG_STORAGE_QUOTA=10**9)
async def test_an_archive_is_admitted_without_holding_a_db_connection(admission_spy):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"a.txt": b"hello"})
    # as asgi_upload does after the auth query
    await sync_to_async(lambda: connection.close())()

    await svc.upload_archive(
        org.id, "", "bundle.zip", _aiter(archive), len(archive), backend=backend
    )

    assert admission_spy.connection_open_at_admission == [False]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_archive_declared_over_the_free_space_is_still_admitted(admission_spy):
    # only the unpacked size counts against the quota, and it is unknown up front
    archive = _zip({"a.txt": b"hello"})
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    with override_settings(ORG_STORAGE_QUOTA=len(archive) - 1, MAX_ARCHIVE_FILE_SIZE=10**6):
        result = await svc.upload_archive(
            org.id, "", "bundle.zip", _aiter(archive), len(archive), backend=backend
        )

    assert result["extracted"] == ["bundle/a.txt"]
    assert admission_spy.admitted == [org.id]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(MAX_ARCHIVE_FILE_SIZE=10, ORG_STORAGE_QUOTA=10**9)
async def test_an_archive_whose_content_length_lies_is_still_stopped_while_read(admission_spy):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(UploadTooLarge):
        await svc.upload_archive(
            org.id, "", "bundle.zip", _aiter(b"x" * 6, b"x" * 6), 5, backend=backend
        )

    assert admission_spy.admitted == [org.id]
    assert not backend._objects


# --- storage unreachable ----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="http://minio:9000"),
        ReadTimeoutError(endpoint_url="http://minio:9000"),
        _client_error(503, "ServiceUnavailable"),
    ],
    ids=["unreachable", "read-timeout", "5xx"],
)
async def test_storage_outages_become_storage_unavailable(error):
    org = await Organization.objects.acreate(name="Acme")

    with pytest.raises(StorageUnavailable):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"x"), 1, backend=_FailingBackend(error))

    assert not await StorageFile.objects.filter(org=org).aexists()


def test_storage_unavailable_tells_the_client_when_to_retry():
    error = StorageUnavailable()

    assert error.status_code == 503
    assert error.headers == {"Retry-After": "30"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_a_storage_4xx_is_a_misconfiguration_not_an_outage():
    org = await Organization.objects.acreate(name="Acme")
    error = _client_error(403, "AccessDenied")

    with pytest.raises(ClientError):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"x"), 1, backend=_FailingBackend(error))


# --- archives -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
@pytest.mark.parametrize("member", ["../evil.txt", "../../etc/cron.d/x", "/etc/passwd"])
async def test_zip_slip_and_absolute_member_names_are_rejected_before_any_write(member):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"fine.txt": b"ok", member: b"evil"})

    with pytest.raises(ValidationError, match="escapes the target folder"):
        await svc.upload_archive(org.id, "docs", "bundle.zip", _aiter(archive), None, backend=backend)

    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_the_archive_is_buffered_off_the_event_loop(monkeypatch):
    # past max_size a SpooledTemporaryFile write spills to disk: never on the loop
    org = await Organization.objects.acreate(name="Acme")
    loop_thread = threading.get_ident()
    write_threads = []

    class _Recording(tempfile.SpooledTemporaryFile):
        def write(self, data):
            write_threads.append(threading.get_ident())
            return super().write(data)

    monkeypatch.setattr(svc.tempfile, "SpooledTemporaryFile", _Recording)
    archive = _zip({"a.txt": b"hello"})
    backend = InMemoryStorageBackend(organization_prefix="")

    await svc.upload_archive(
        org.id, "", "bundle.zip", _aiter(archive[:20], archive[20:]), None, backend=backend
    )

    assert len(write_threads) == 2
    assert loop_thread not in write_threads


# --- _reserve_folder --------------------------------------------------------------


class _LockWatchingBackend(InMemoryStorageBackend):
    """Records whether a DB transaction (and so a row lock) is open at each S3 call."""

    def __init__(self):
        super().__init__(organization_prefix="")
        self.calls: list[tuple[str, bool]] = []

    def unique_key(self, key, is_folder=False):
        self.calls.append(("unique_key", connection.in_atomic_block))
        return super().unique_key(key, is_folder)

    def claim_folder(self, path):
        self.calls.append(("claim_folder", connection.in_atomic_block))
        return super().claim_folder(path)


def test_reserve_folder_claims_the_wanted_name_when_it_is_free():
    backend = InMemoryStorageBackend(organization_prefix="")

    assert svc._reserve_folder(7, "bundle", backend) == "org_7/bundle"
    assert "org_7/bundle/" in backend._objects


def test_reserve_folder_takes_the_next_free_name_when_the_wanted_one_exists():
    backend = InMemoryStorageBackend(organization_prefix="")
    backend.put_bytes("org_7/bundle/old.txt", b"x")

    assert svc._reserve_folder(7, "bundle", backend) == "org_7/bundle (1)"


def test_reserve_folder_treats_a_file_of_the_same_name_as_taken():
    backend = InMemoryStorageBackend(organization_prefix="")
    backend.put_bytes("org_7/report", b"keep me")

    assert svc._reserve_folder(7, "report", backend) == "org_7/report (1)"
    assert backend._objects["org_7/report"][0] == b"keep me"
    assert "org_7/report (1)/" in backend._objects


def test_reserve_folder_skips_a_name_held_by_both_a_folder_and_a_file():
    # Plain S3 lets "report" and "report/..." coexist; neither leaves the name free.
    backend = InMemoryStorageBackend(organization_prefix="")
    backend.put_bytes("org_7/report/old.txt", b"x")
    backend.put_bytes("org_7/report", b"keep me")

    assert svc._reserve_folder(7, "report", backend) == "org_7/report (1)"


def test_reserve_folder_skips_both_a_folder_and_a_file_holding_names():
    backend = InMemoryStorageBackend(organization_prefix="")
    backend.put_bytes("org_7/report/old.txt", b"x")
    backend.put_bytes("org_7/report (1)", b"a file named like the next folder")

    assert svc._reserve_folder(7, "report", backend) == "org_7/report (2)"


def test_reserve_folder_moves_on_when_a_same_name_file_lands_before_the_claim():
    class _FileRaced(InMemoryStorageBackend):
        """A plain upload of "report" lands between this upload's probe and claim."""

        raced = False

        def claim_folder(self, path):
            if not self.raced:
                self.raced = True
                self.put_bytes(path.rstrip("/"), b"raced in")
            return super().claim_folder(path)

    backend = _FileRaced(organization_prefix="")

    assert svc._reserve_folder(7, "report", backend) == "org_7/report (1)"
    assert backend._objects["org_7/report"][0] == b"raced in"
    assert "org_7/report/" not in backend._objects


def test_in_memory_backend_refuses_a_key_under_a_file_like_minio():
    backend = InMemoryStorageBackend(organization_prefix="")
    backend.put_bytes("org_7/report", b"keep me")

    with pytest.raises(ClientError) as caught:
        backend.put_bytes("org_7/report/a.txt", b"a")
    assert caught.value.response["Error"]["Code"] == "XMinioParentIsObject"
    assert caught.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    assert list(backend._objects) == ["org_7/report"]


def test_reserve_folder_gives_up_on_a_store_that_refuses_every_claim():
    class _RefusesEveryClaim(InMemoryStorageBackend):
        claims = 0

        def claim_folder(self, path):
            self.claims += 1
            return False

    backend = _RefusesEveryClaim(organization_prefix="")

    with pytest.raises(StorageUnavailable) as caught:
        svc._reserve_folder(7, "bundle", backend)
    assert caught.value.status_code == 503
    assert caught.value.headers == {"Retry-After": "30"}
    assert backend.claims == svc._MAX_FOLDER_CLAIMS


@pytest.mark.django_db(transaction=True)
def test_reserve_folder_moves_on_when_a_concurrent_upload_claims_the_same_name():
    org = Organization.objects.create(name="Acme")

    class _Raced(_LockWatchingBackend):
        """Another upload claims every name between this one's probe and claim, once."""

        raced = False

        def claim_folder(self, path):
            if not self.raced:
                self.raced = True
                InMemoryStorageBackend.claim_folder(self, path)  # the competitor wins
            return super().claim_folder(path)

    backend = _Raced()

    key = svc._reserve_folder(org.id, "bundle", backend)

    assert key == f"org_{org.id}/bundle (1)"
    assert {f"org_{org.id}/bundle/", f"org_{org.id}/bundle (1)/"} <= set(backend._objects)
    assert not any(in_transaction for _, in_transaction in backend.calls)
