import asyncio
import io
import tarfile
import zipfile
from unittest.mock import AsyncMock

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from tables.models import Organization, StorageFile
from tables.services.storage_service import upload_stream_service as svc
from tables.exceptions import StorageQuotaExceeded, UploadTooLarge
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
    """Async backend double: upload_chunks optionally drives size_guard."""

    def __init__(self, returned_size=None, guard_totals=None):
        self._returned_size = returned_size
        self._guard_totals = guard_totals or []
        self.upload_chunks = AsyncMock(side_effect=self._upload_chunks)

    async def _upload_chunks(
        self, path, chunks, *, part_size, size_guard=None, before_commit=None
    ):
        if self._guard_totals:
            for total in self._guard_totals:
                if size_guard is not None:
                    size_guard(total)
            size = self._guard_totals[-1]
        else:
            async for _ in chunks:
                pass
            size = self._returned_size
        if before_commit is not None:
            await before_commit(size)
        return size


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_upload_file_happy():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=10)
    result = await svc.upload_file(
        org.id, "docs", "a.txt", _aiter(b"0123456789"), 10, backend=backend
    )
    assert result == {"path": "docs/a.txt", "size": 10}
    backend.upload_chunks.assert_awaited_once()
    assert backend.upload_chunks.await_args.args[0] == "org_{}/docs/a.txt".format(org.id)
    row = await StorageFile.objects.aget(org=org, path="docs/a.txt")
    assert row.size == 10


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_upload_file_rejected_row_leaves_no_object():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    with pytest.raises(StorageQuotaExceeded):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"x" * 10), None, backend=backend)
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org, path="a.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_upload_file_midstream_guard_aborts():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(guard_totals=[4, 8])
    with pytest.raises(StorageQuotaExceeded):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"x"), None, backend=backend)
    assert not await StorageFile.objects.filter(org=org, path="a.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_upload_archive_happy():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"a.txt": b"hello", "sub/b.txt": b"world"})
    result = await svc.upload_archive(
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
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_upload_archive_past_free_space_writes_nothing():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    archive = _zip({"big.txt": b"0123456789"})  # 10 > free 5
    with pytest.raises(StorageQuotaExceeded):
        await svc.upload_archive(
            org.id, "", "bundle.zip", _aiter(archive.read()), backend=backend
        )
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org, path__startswith="bundle-").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_upload_file_has_no_per_file_cap_by_default():
    org = await Organization.objects.acreate(name="Acme")
    huge = 500 * 1024 * 1024
    backend = _FakeFlatBackend(guard_totals=[huge])
    result = await svc.upload_file(org.id, "", "big.bin", _aiter(b"x"), huge, backend=backend)
    assert result["size"] == huge


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=100)
async def test_upload_file_honours_cap_when_configured():
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=10)
    with pytest.raises(UploadTooLarge):
        await svc.upload_file(org.id, "", "big.bin", _aiter(b"x"), 200, backend=backend)
    backend.upload_chunks.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_semaphore_caps_concurrent_uploads(monkeypatch):
    org = await Organization.objects.acreate(name="Acme")
    monkeypatch.setattr(svc, "_slots", asyncio.Semaphore(2))

    in_flight = 0
    peak = 0
    release = asyncio.Event()

    class _Blocking(_FakeFlatBackend):
        async def _upload_chunks(
            self, path, chunks, *, part_size, size_guard=None, before_commit=None
        ):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1
            return 1

    async def _one(i):
        await svc.upload_file(
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
async def test_upload_archive_stores_a_non_archive_as_a_plain_file():
    # routing happens on the name, so a plain file named .zip reaches the archive
    # branch; the non-streaming upload stored it as a file and so must this one
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    body = b"not an archive at all, just text"

    result = await svc.upload_archive(org.id, "docs", "notes.zip", _aiter(body), backend=backend)

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
        await svc.upload_archive(
            org.id, "", "notes.zip", _aiter(b"x" * 50), backend=backend
        )
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_upload_archive_extracts_a_tbz_alias():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        info = tarfile.TarInfo("a.txt")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"hello"))

    result = await svc.upload_archive(
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
async def test_upload_file_rejects_or_canonicalises_odd_paths(path, filename):
    # the object key and the StorageFile row must never disagree: normalising only
    # the key used to leave rows like "/etc/passwd" and phantom "/" folders behind
    org = await Organization.objects.acreate(name="Acme")
    backend = _FakeFlatBackend(returned_size=1)

    try:
        result = await svc.upload_file(org.id, path, filename, _aiter(b"x"), None, backend=backend)
    except ValidationError:
        return  # rejected outright is an acceptable outcome for a malformed name

    key = backend.upload_chunks.await_args.args[0]
    assert key == f"org_{org.id}/{result['path']}"
    assert await StorageFile.objects.filter(org=org, path=result["path"]).aexists()
    assert ".." not in result["path"]
    assert not result["path"].startswith(("/", "./"))
    assert "//" not in result["path"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_upload_archive_rejects_a_bad_path_before_reading_the_body():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    consumed = []

    async def _watched():
        consumed.append(True)
        yield b"x"

    with pytest.raises(ValidationError):
        await svc.upload_archive(org.id, "../escape", "b.zip", _watched(), backend=backend)
    assert not consumed  # body never touched


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_encrypted_archive_is_rejected_before_anything_is_written():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plain.txt", "readable")
        zf.writestr("secret.txt", "data")
    raw = bytearray(buf.getvalue())
    raw[6] |= 0x01
    cd = raw.find(b"PK\x01\x02")
    raw[cd + 8] |= 0x01

    with pytest.raises(ValidationError, match="password-protected"):
        await svc.upload_archive(org.id, "", "secret.zip", _aiter(bytes(raw)), backend=backend)

    # the pre-flight runs before extraction, so not even the readable member lands
    assert not backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_damaged_archive_answers_400_instead_of_a_server_fault():
    # a corrupt member body raises zipfile.BadZipFile, which is NOT a ValueError:
    # uncaught it would reach the handler's catch-all and be logged as our fault
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "x" * 5000)
    raw = bytearray(buf.getvalue())
    raw[60:200] = b"\xff" * 140

    with pytest.raises(ValidationError):
        await svc.upload_archive(org.id, "", "broken.zip", _aiter(bytes(raw)), backend=backend)
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=100, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_overwrite_is_charged_only_the_size_difference():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.upload_file(org.id, "", "a.txt", _aiter(b"x" * 80), 80, backend=backend)

    result = await svc.upload_file(org.id, "", "a.txt", _aiter(b"y" * 90), 90, backend=backend)

    assert result == {"path": "a.txt", "size": 90}
    assert backend._objects[f"org_{org.id}/a.txt"][0] == b"y" * 90


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**6, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_failed_overwrite_keeps_the_previous_file(monkeypatch):
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.upload_file(org.id, "", "a.txt", _aiter(b"old"), 3, backend=backend)

    def _raced(*_args, **_kwargs):
        raise StorageQuotaExceeded()

    monkeypatch.setattr(svc, "record_files_within_quota", _raced)
    with pytest.raises(StorageQuotaExceeded):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"new!"), 4, backend=backend)

    assert backend._objects[f"org_{org.id}/a.txt"][0] == b"old"
    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 3


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(
    ORG_STORAGE_QUOTA=10**9,
    UPLOAD_PART_SIZE=8,
    ARCHIVE_UPLOAD_CONCURRENCY=2,
)
async def test_archive_members_small_and_large_all_land():
    # part_size 8: "tiny" goes through the PUT pool, "big" streams through upload()
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    members = {f"s{i}.txt": b"tiny" for i in range(5)} | {"big.bin": b"0123456789abcdef"}
    archive = _zip(members)

    result = await svc.upload_archive(
        org.id, "", "bundle.zip", _aiter(archive.read()), backend=backend
    )

    for name, data in members.items():
        assert backend._objects[f"org_{org.id}/{result['path']}/{name}"][0] == data
        row = await StorageFile.objects.aget(org=org, path=f"{result['path']}/{name}")
        assert row.size == len(data)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**6, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_failed_commit_after_the_row_restores_the_row():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    await svc.upload_file(org.id, "", "a.txt", _aiter(b"old"), 3, backend=backend)

    def _commit_fails(*_args, **_kwargs):
        raise ConnectionError("minio went away")

    backend.put_bytes = _commit_fails
    with pytest.raises(ConnectionError):
        await svc.upload_file(org.id, "", "a.txt", _aiter(b"new!"), 4, backend=backend)
    with pytest.raises(ConnectionError):
        await svc.upload_file(org.id, "", "b.txt", _aiter(b"new!"), 4, backend=backend)

    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 3
    assert not await StorageFile.objects.filter(org=org, path="b.txt").aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_empty_archive_folders_are_created():
    org = await Organization.objects.acreate(name="Acme")
    backend = InMemoryStorageBackend(organization_prefix="")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("empty/"), b"")
        zf.writestr("full/a.txt", b"x")

    result = await svc.upload_archive(org.id, "", "b.zip", _aiter(buf.getvalue()), backend=backend)

    assert f"org_{org.id}/{result['path']}/empty/" in backend._objects
    assert await StorageFile.objects.filter(
        org=org, path=f"{result['path']}/empty/", item_type="folder"
    ).aexists()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@override_settings(ORG_STORAGE_QUOTA=10**9)
@pytest.mark.parametrize("filename", ["new\nline.txt", "tab\tname.txt", " "])
async def test_upload_file_rejects_unprintable_or_blank_names(filename):
    org = await Organization.objects.acreate(name="Acme")
    with pytest.raises(ValidationError):
        await svc.upload_file(org.id, "", filename, _aiter(b"x"), 1, backend=_FakeFlatBackend(1))
