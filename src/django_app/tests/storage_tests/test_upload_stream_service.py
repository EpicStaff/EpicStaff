import asyncio
import io
import tarfile
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from tables.models import Organization, StorageFile
from tables.services.storage_service import upload_stream_service as svc
from tables.services.storage_service.quota_service import StorageQuotaExceeded
from tables.services.storage_service.upload_stream_service import UploadTooLarge
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


async def _aiter(*chunks):
    for c in chunks:
        yield c


def _zip(members: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


class _FakeFlatBackend:
    """Async backend double: stream_upload optionally drives size_guard."""

    def __init__(self, returned_size=None, guard_totals=None):
        self._returned_size = returned_size
        self._guard_totals = guard_totals or []
        self.stream_upload = AsyncMock(side_effect=self._stream_upload)
        self.delete_object_async = AsyncMock()
        self.exists = MagicMock(return_value=False)
        self.promote_object = MagicMock()

    async def _stream_upload(self, path, chunk_aiter, *, part_size, size_guard=None):
        if self._guard_totals:
            for total in self._guard_totals:
                if size_guard is not None:
                    size_guard(total)
            return self._guard_totals[-1]
        async for _ in chunk_aiter:
            pass
        return self._returned_size


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_ingest_flat_happy():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=10)
    result = await svc.ingest_flat(
        org.id, "docs", "a.txt", _aiter(b"0123456789"), 10, backend=backend
    )
    assert result == {"path": "docs/a.txt", "size": 10}
    backend.stream_upload.assert_awaited_once()
    assert backend.stream_upload.await_args.args[0] == "org_{}/docs/a.txt".format(org.id)
    row = await StorageFile.objects.aget(org=org, path="docs/a.txt")
    assert row.size == 10


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_ingest_flat_commit_race_deletes_object():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=10)
    with pytest.raises(StorageQuotaExceeded):
        await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"x"), None, backend=backend)
    backend.delete_object_async.assert_awaited_once()
    assert not await StorageFile.objects.filter(org=org, path="a.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_ingest_flat_midstream_guard_aborts_no_delete():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(guard_totals=[4, 8])
    with pytest.raises(StorageQuotaExceeded):
        await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"x"), None, backend=backend)
    backend.delete_object_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_ARCHIVE_UNCOMPRESSED_SIZE=10**6)
async def test_ingest_archive_happy():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"a.txt": b"hello", "sub/b.txt": b"world"})
    result = await svc.ingest_archive(
        org.id, "", "bundle.zip", _aiter(archive.read()), backend=backend
    )
    assert result["path"].startswith("bundle-")
    assert sorted(result["extracted"]) == sorted(
        [f"{result['path']}/a.txt", f"{result['path']}/sub/b.txt"]
    )
    assert f"org_{org.id}/{result['path']}/a.txt" in backend._objects
    assert await StorageFile.objects.filter(
        org=org, path=f"{result['path']}/a.txt"
    ).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_ARCHIVE_UNCOMPRESSED_SIZE=5)
async def test_ingest_archive_bomb_cleanup():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"big.txt": b"0123456789"})  # 10 > cap 5
    with pytest.raises(Exception):
        await svc.ingest_archive(
            org.id, "", "bundle.zip", _aiter(archive.read()), backend=backend
        )
    assert not await StorageFile.objects.filter(org=org, path__startswith="bundle-").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_ingest_flat_has_no_per_file_cap_by_default():
    org = await Organization.objects.acreate(name="Acme")
    huge = 500 * 1024 * 1024
    backend = _FakeFlatBackend(guard_totals=[huge])
    result = await svc.ingest_flat(org.id, "", "big.bin", _aiter(b"x"), huge, backend=backend)
    assert result["size"] == huge


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=100)
async def test_ingest_flat_honours_cap_when_configured():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=10)
    with pytest.raises(UploadTooLarge):
        await svc.ingest_flat(org.id, "", "big.bin", _aiter(b"x"), 200, backend=backend)
    backend.stream_upload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_semaphore_caps_concurrent_uploads(monkeypatch):
    org = await Organization.objects.acreate(name="Acme")
    monkeypatch.setattr(svc, "_semaphore", asyncio.Semaphore(2))

    in_flight = 0
    peak = 0
    release = asyncio.Event()

    class _Blocking(_FakeFlatBackend):
        async def _stream_upload(self, path, chunk_aiter, *, part_size, size_guard=None):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1
            return 1

    async def _one(i):
        await svc.ingest_flat(
            org.id, "", f"f{i}.bin", _aiter(b"x"), None, backend=_Blocking(returned_size=1)
        )

    tasks = [asyncio.create_task(_one(i)) for i in range(5)]
    await asyncio.sleep(0.05)
    assert peak == 2
    release.set()
    await asyncio.gather(*tasks)
    assert peak == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_ingest_archive_stores_a_non_archive_as_a_plain_file():
    # routing happens on the name, so a plain file named .zip reaches the archive
    # branch; the non-streaming upload stored it as a file and so must this one
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    body = b"not an archive at all, just text"

    result = await svc.ingest_archive(org.id, "docs", "notes.zip", _aiter(body), backend=backend)

    assert result == {"path": "docs/notes.zip", "size": len(body)}
    assert backend._objects[f"org_{org.id}/docs/notes.zip"][0] == body
    row = await StorageFile.objects.aget(org=org, path="docs/notes.zip")
    assert row.size == len(body)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_non_archive_fallback_still_honours_the_quota():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    with pytest.raises(StorageQuotaExceeded):
        await svc.ingest_archive(
            org.id, "", "notes.zip", _aiter(b"x" * 50), backend=backend
        )
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_ARCHIVE_UNCOMPRESSED_SIZE=10**6)
async def test_ingest_archive_extracts_a_tbz_alias():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        info = tarfile.TarInfo("a.txt")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"hello"))

    result = await svc.ingest_archive(
        org.id, "", "bundle.tbz", _aiter(buf.getvalue()), backend=backend
    )

    assert result["extracted"] == [f"{result['path']}/a.txt"]
    assert f"org_{org.id}/{result['path']}/a.txt" in backend._objects


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
@pytest.mark.parametrize(
    ("path", "filename"),
    [
        ("", "/etc/passwd"),
        ("sectest", "a//b.txt"),
        ("./sectest", "dot.txt"),
        ("sectest", "sub/nested.txt"),
    ],
)
async def test_ingest_flat_rejects_or_canonicalises_odd_paths(path, filename):
    # the object key and the StorageFile row must never disagree: normalising only
    # the key used to leave rows like "/etc/passwd" and phantom "/" folders behind
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=1)

    try:
        result = await svc.ingest_flat(org.id, path, filename, _aiter(b"x"), None, backend=backend)
    except ValidationError:
        return  # rejected outright is an acceptable outcome for a malformed name

    key = backend.stream_upload.await_args.args[0]
    assert key == f"org_{org.id}/{result['path']}"
    assert await StorageFile.objects.filter(org=org, path=result["path"]).aexists()
    assert ".." not in result["path"]
    assert not result["path"].startswith(("/", "./"))
    assert "//" not in result["path"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_ingest_archive_rejects_a_bad_path_before_reading_the_body():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    consumed = []

    async def _watched():
        consumed.append(True)
        yield b"x"

    with pytest.raises(ValidationError):
        await svc.ingest_archive(org.id, "../escape", "b.zip", _watched(), backend=backend)
    assert not consumed  # body never touched


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=100, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_overwrite_is_charged_only_the_size_difference():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"x" * 80), 80, backend=backend)

    result = await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"y" * 90), 90, backend=backend)

    assert result == {"path": "a.txt", "size": 90}
    assert backend._objects[f"org_{org.id}/a.txt"][0] == b"y" * 90
    assert not [k for k in backend._objects if k.startswith(svc._STAGING_PREFIX)]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**6, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_failed_overwrite_keeps_the_previous_file(monkeypatch):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"old"), 3, backend=backend)

    def _raced(*_args, **_kwargs):
        raise StorageQuotaExceeded()

    monkeypatch.setattr(svc, "commit_under_org_lock", _raced)
    with pytest.raises(StorageQuotaExceeded):
        await svc.ingest_flat(org.id, "", "a.txt", _aiter(b"new!"), 4, backend=backend)

    assert backend._objects[f"org_{org.id}/a.txt"][0] == b"old"
    assert not [k for k in backend._objects if k.startswith(svc._STAGING_PREFIX)]
    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 3


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    ORG_STORAGE_QUOTA=10**9,
    MAX_ARCHIVE_UNCOMPRESSED_SIZE=10**6,
    UPLOAD_PART_SIZE=8,
    ARCHIVE_UPLOAD_CONCURRENCY=2,
)
async def test_archive_members_small_and_large_all_land():
    # part_size 8: "tiny" goes through the PUT pool, "big" streams through upload()
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    members = {f"s{i}.txt": b"tiny" for i in range(5)} | {"big.bin": b"0123456789abcdef"}
    archive = _zip(members)

    result = await svc.ingest_archive(
        org.id, "", "bundle.zip", _aiter(archive.read()), backend=backend
    )

    for name, data in members.items():
        assert backend._objects[f"org_{org.id}/{result['path']}/{name}"][0] == data
        row = await StorageFile.objects.aget(org=org, path=f"{result['path']}/{name}")
        assert row.size == len(data)
