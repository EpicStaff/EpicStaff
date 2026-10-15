import io
import tarfile
import zipfile

import pytest
from django.db import connection
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from tables.exceptions import StoragePathIsFile, StorageQuotaExceeded, StorageUnavailable
from tables.models import StorageFile
from tables.services.storage_service.upload import archive_upload, file_upload
from tables.services.storage_service.base import StorageUnreachable
from tests.storage_tests.in_memory_backend import (
    FailingInMemoryBackend,
    InMemoryStorageBackend,
    async_chunks,
    zip_bytes,
)

pytestmark = [pytest.mark.django_db(transaction=True)]


def _encrypted_zip() -> bytes:
    raw = bytearray(zip_bytes({"plain.txt": b"readable", "secret.txt": b"data"}))
    raw[6] |= 0x01
    directory = raw.find(b"PK\x01\x02")
    raw[directory + 8] |= 0x01
    return bytes(raw)


def _damaged_member_zip() -> bytes:
    # a corrupt member body raises zipfile.BadZipFile, which is NOT a ValueError:
    # uncaught it would reach the handler's catch-all and be logged as our fault
    raw = bytearray(zip_bytes({"a.txt": b"x" * 5000}))
    raw[60:200] = b"\xff" * 140
    return bytes(raw)


def _long_name_bomb_tgz() -> bytes:
    """A 1 MiB GNU long-name header (over the 64 KiB bound) in about 1 KiB of .tar.gz."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
        info = tarfile.TarInfo("a" * (1024 * 1024))
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    return buffer.getvalue()


def _deflate64_zip() -> bytes:
    raw = bytearray(zip_bytes({"a.txt": b"data"}))
    raw[8:10] = (9).to_bytes(2, "little")  # local header: Deflate64
    directory = raw.find(b"PK\x01\x02")
    raw[directory + 10 : directory + 12] = (9).to_bytes(2, "little")  # central directory
    return bytes(raw)


# --- plain files ---


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_upload_file_stores_the_object_and_its_row(org, fake_backend):
    result = await file_upload.upload_file(
        org.id, "docs", "a.txt", async_chunks(b"01234", b"56789"), 10, backend=fake_backend
    )

    assert result == {"path": "docs/a.txt", "size": 10}
    assert fake_backend._objects[f"org_{org.id}/docs/a.txt"][0] == b"0123456789"
    assert (await StorageFile.objects.aget(org=org, path="docs/a.txt")).size == 10


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_a_file_past_the_quota_mid_stream_leaves_no_object_and_no_row(org, fake_backend):
    with pytest.raises(StorageQuotaExceeded):
        await file_upload.upload_file(
            org.id, "", "a.txt", async_chunks(b"x" * 10), None, backend=fake_backend
        )

    assert not fake_backend._objects
    assert not await StorageFile.objects.filter(org=org, path="a.txt").aexists()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**12, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_upload_file_has_no_per_file_cap_when_none_is_configured(org, fake_backend):
    huge = 500 * 1024 * 1024

    result = await file_upload.upload_file(
        org.id, "", "big.bin", async_chunks(b"x"), huge, backend=fake_backend
    )

    assert result["size"] == 1


@pytest.mark.asyncio
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
async def test_upload_file_rejects_or_canonicalises_odd_paths(org, fake_backend, path, filename):
    # the object key and the StorageFile row must never disagree: normalising only
    # the key used to leave rows like "/etc/passwd" and phantom "/" folders behind
    try:
        result = await file_upload.upload_file(
            org.id, path, filename, async_chunks(b"x"), None, backend=fake_backend
        )
    except ValidationError:
        return  # rejected outright is an acceptable outcome for a malformed name

    assert list(fake_backend._objects) == [f"org_{org.id}/{result['path']}"]
    assert await StorageFile.objects.filter(org=org, path=result["path"]).aexists()
    assert ".." not in result["path"]
    assert not result["path"].startswith(("/", "./"))
    assert "//" not in result["path"]


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9)
@pytest.mark.parametrize("filename", ["new\nline.txt", "tab\tname.txt", " "])
async def test_upload_file_rejects_unprintable_or_blank_names(org, fake_backend, filename):
    with pytest.raises(ValidationError):
        await file_upload.upload_file(org.id, "", filename, async_chunks(b"x"), 1, backend=fake_backend)


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=100, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_an_overwrite_is_charged_only_the_size_difference(org, fake_backend):
    await file_upload.upload_file(org.id, "", "a.txt", async_chunks(b"x" * 80), 80, backend=fake_backend)

    result = await file_upload.upload_file(
        org.id, "", "a.txt", async_chunks(b"y" * 90), 90, backend=fake_backend
    )

    assert result == {"path": "a.txt", "size": 90}
    assert fake_backend._objects[f"org_{org.id}/a.txt"][0] == b"y" * 90


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**6, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_a_rejected_overwrite_keeps_the_previous_file(org, fake_backend, monkeypatch):
    await file_upload.upload_file(org.id, "", "a.txt", async_chunks(b"old"), 3, backend=fake_backend)

    def _raced(*_args, **_kwargs):
        raise StorageQuotaExceeded()

    monkeypatch.setattr(file_upload, "record_files_within_quota", _raced)
    with pytest.raises(StorageQuotaExceeded):
        await file_upload.upload_file(org.id, "", "a.txt", async_chunks(b"new!"), 4, backend=fake_backend)

    assert fake_backend._objects[f"org_{org.id}/a.txt"][0] == b"old"
    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 3


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**6, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_a_failed_commit_after_the_row_restores_the_row(org, monkeypatch):
    backend = InMemoryStorageBackend()
    await file_upload.upload_file(org.id, "", "a.txt", async_chunks(b"old"), 3, backend=backend)

    def _commit_fails(*_args, **_kwargs):
        raise StorageUnreachable("storage went away")

    monkeypatch.setattr(backend, "put_bytes", _commit_fails)
    for filename in ("a.txt", "b.txt"):
        with pytest.raises(StorageUnavailable):
            await file_upload.upload_file(org.id, "", filename, async_chunks(b"new!"), 4, backend=backend)

    assert (await StorageFile.objects.aget(org=org, path="a.txt")).size == 3
    assert not await StorageFile.objects.filter(org=org, path="b.txt").aexists()


# --- archives ---


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, ARCHIVE_UPLOAD_CONCURRENCY=2)
async def test_upload_archive_unpacks_every_member_and_empty_folder_with_rows(org):
    # part_size 8: "tiny" members go through the PUT pool, "big.bin" streams
    backend = InMemoryStorageBackend(part_size=8)
    members = {f"sub/s{index}.txt": b"tiny" for index in range(5)} | {
        "big.bin": b"0123456789abcdef"
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("empty/"), b"")
        for name, data in members.items():
            archive.writestr(name, data)

    result = await archive_upload.upload_archive(
        org.id, "", "bundle.zip", async_chunks(buffer.getvalue()), None, backend=backend
    )

    assert result["path"] == "bundle"
    assert sorted(result["extracted"]) == sorted(f"bundle/{name}" for name in members)
    for name, data in members.items():
        assert backend._objects[f"org_{org.id}/bundle/{name}"][0] == data
        assert (await StorageFile.objects.aget(org=org, path=f"bundle/{name}")).size == len(data)
    assert f"org_{org.id}/bundle/empty/" in backend._objects
    assert await StorageFile.objects.filter(
        org=org, path="bundle/empty/", item_type="folder"
    ).aexists()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_the_same_archive_twice_unpacks_into_the_next_free_folder(org, fake_backend):
    archive = zip_bytes({"a.txt": b"hello"})

    first = await archive_upload.upload_archive(
        org.id, "", "bundle.zip", async_chunks(archive), None, backend=fake_backend
    )
    second = await archive_upload.upload_archive(
        org.id, "", "bundle.zip", async_chunks(archive), None, backend=fake_backend
    )

    assert (first["path"], second["path"]) == ("bundle", "bundle (1)")
    assert second["extracted"] == ["bundle (1)/a.txt"]


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=5)
async def test_an_archive_unpacking_past_the_free_space_writes_nothing(org, fake_backend):
    archive = zip_bytes({"big.txt": b"0123456789"})  # 10 > free 5

    with pytest.raises(StorageQuotaExceeded):
        await archive_upload.upload_archive(
            org.id, "", "bundle.zip", async_chunks(archive), None, backend=fake_backend
        )

    assert not fake_backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_a_non_archive_with_an_archive_name_is_stored_as_a_plain_file(org, fake_backend):
    # routing happens on the name, so a plain file named .zip reaches the archive branch
    body = b"not an archive at all, just text"

    result = await archive_upload.upload_archive(
        org.id, "docs", "notes.zip", async_chunks(body), None, backend=fake_backend
    )

    assert result == {"path": "docs/notes.zip", "size": len(body)}
    assert fake_backend._objects[f"org_{org.id}/docs/notes.zip"][0] == body
    assert (await StorageFile.objects.aget(org=org, path="docs/notes.zip")).size == len(body)


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=5, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_a_non_archive_with_an_archive_name_still_honours_the_quota(org, fake_backend):
    with pytest.raises(StorageQuotaExceeded):
        await archive_upload.upload_archive(
            org.id, "", "notes.zip", async_chunks(b"x" * 50), None, backend=fake_backend
        )

    assert not fake_backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9)
async def test_upload_archive_rejects_a_bad_path_before_reading_the_body(org, fake_backend):
    consumed = []

    async def _watched():
        consumed.append(True)
        yield b"x"

    with pytest.raises(ValidationError):
        await archive_upload.upload_archive(
            org.id, "../escape", "b.zip", _watched(), None, backend=fake_backend
        )
    assert not consumed


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9)
@pytest.mark.parametrize(
    ("filename", "body", "match"),
    [
        ("secret.zip", _encrypted_zip(), "password-protected"),
        ("broken.zip", _damaged_member_zip(), None),
        ("x.tar.gz", _long_name_bomb_tgz(), "tar header of"),
        ("d64.zip", _deflate64_zip(), "unsupported method"),
        (
            "slip.zip",
            zip_bytes({"fine.txt": b"ok", "../evil.txt": b"evil"}),
            "escapes the target folder",
        ),
        (
            "slip.zip",
            zip_bytes({"fine.txt": b"ok", "../../etc/cron.d/x": b"evil"}),
            "escapes the target folder",
        ),
        (
            "abs.zip",
            zip_bytes({"fine.txt": b"ok", "/etc/passwd": b"evil"}),
            "escapes the target folder",
        ),
    ],
    ids=[
        "encrypted",
        "damaged",
        "tar-header-bomb",
        "deflate64",
        "zip-slip",
        "deep-zip-slip",
        "absolute",
    ],
)
async def test_a_hostile_or_damaged_archive_answers_400_and_writes_nothing(
    org, fake_backend, filename, body, match
):
    with pytest.raises(ValidationError, match=match):
        await archive_upload.upload_archive(
            org.id, "", filename, async_chunks(body), None, backend=fake_backend
        )

    assert not fake_backend._objects
    assert not await StorageFile.objects.filter(org=org).aexists()


# --- archive folder naming and cleanup ---


async def _upload_report_file(org, backend) -> str:
    """The user's own plain file "report", named exactly like report.zip's folder."""
    await file_upload.upload_file(org.id, "", "report", async_chunks(b"keep me"), 7, backend=backend)
    return f"org_{org.id}/report"


def _keys_under(backend, folder_key: str) -> list[str]:
    return [key for key in backend._objects if key.startswith(folder_key + "/")]


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_an_archive_named_like_a_file_unpacks_into_the_next_free_folder(org, fake_backend):
    # the store refuses keys under the object "report", so "report/" is not free
    report_key = await _upload_report_file(org, fake_backend)

    result = await archive_upload.upload_archive(
        org.id,
        "",
        "report.zip",
        async_chunks(zip_bytes({"a.txt": b"a"})),
        None,
        backend=fake_backend,
    )

    assert result == {"path": "report (1)", "extracted": ["report (1)/a.txt"]}
    assert fake_backend._objects[report_key][0] == b"keep me"
    assert _keys_under(fake_backend, report_key) == []
    assert fake_backend._objects[f"{report_key} (1)/a.txt"][0] == b"a"
    assert await StorageFile.objects.filter(org=org, path="report", item_type="file").aexists()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
async def test_an_archive_skips_a_file_named_like_the_next_free_folder(org, fake_backend):
    archive = zip_bytes({"a.txt": b"a"})
    await archive_upload.upload_archive(
        org.id, "", "report.zip", async_chunks(archive), None, backend=fake_backend
    )
    await file_upload.upload_file(
        org.id, "", "report (1)", async_chunks(b"keep me"), 7, backend=fake_backend
    )

    result = await archive_upload.upload_archive(
        org.id, "", "report.zip", async_chunks(archive), None, backend=fake_backend
    )

    assert result["path"] == "report (2)"
    assert fake_backend._objects[f"org_{org.id}/report (1)"][0] == b"keep me"


def _quota_raced(*_args, **_kwargs):
    # another upload used the space between the pre-flight and the row write
    raise StorageQuotaExceeded()


@pytest.mark.asyncio
@override_settings(ORG_STORAGE_QUOTA=10**9, MAX_STREAM_UPLOAD_FILE_SIZE=None)
@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [("storage-outage", StorageUnavailable), ("quota-race", StorageQuotaExceeded)],
)
async def test_a_failed_unpack_removes_what_it_created_but_keeps_a_file_named_like_the_folder(
    org, monkeypatch, failure, expected_error
):
    if failure == "storage-outage":
        backend = FailingInMemoryBackend("/report (1)/c.txt")
    else:
        backend = InMemoryStorageBackend()
    report_key = await _upload_report_file(org, backend)
    if failure == "quota-race":
        # Only the archive's row write races; the plain file above must land.
        monkeypatch.setattr(archive_upload, "record_files_within_quota", _quota_raced)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("empty/"), b"")
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            archive.writestr(name, name.encode())

    with pytest.raises(expected_error):
        await archive_upload.upload_archive(
            org.id, "", "report.zip", async_chunks(buffer.getvalue()), None, backend=backend
        )

    assert backend._objects[report_key][0] == b"keep me"
    # members, the empty-folder marker and the claimed folder marker are all gone
    assert _keys_under(backend, f"{report_key} (1)") == []
    assert f"{report_key} (1)/" not in backend._objects
    assert await StorageFile.objects.filter(org=org, path="report", item_type="file").aexists()
    assert not await StorageFile.objects.filter(org=org, path__startswith="report (1)").aexists()


# --- _reserve_folder races (not reachable through one upload) ---


def test_reserve_folder_moves_on_when_a_same_name_file_lands_before_the_claim():
    class _FileRaced(InMemoryStorageBackend):
        """A plain upload of "report" lands between this upload's probe and claim."""

        raced = False

        def claim_folder(self, path):
            if not self.raced:
                self.raced = True
                self.put_bytes(path.rstrip("/"), b"raced in")
            return super().claim_folder(path)

    backend = _FileRaced()

    assert archive_upload._reserve_folder(7, "report", backend) == "org_7/report (1)"
    assert backend._objects["org_7/report"][0] == b"raced in"
    assert "org_7/report/" not in backend._objects


def test_reserve_folder_moves_on_when_a_concurrent_upload_claims_the_same_name(org):
    class _Raced(InMemoryStorageBackend):
        """Another upload claims the name between this one's probe and claim, once;
        records whether a DB transaction (and so a row lock) is open at each call."""

        raced = False

        def __init__(self):
            super().__init__()
            self.calls: list[tuple[str, bool]] = []

        def unique_key(self, key, is_folder=False):
            self.calls.append(("unique_key", connection.in_atomic_block))
            return super().unique_key(key, is_folder)

        def claim_folder(self, path):
            self.calls.append(("claim_folder", connection.in_atomic_block))
            if not self.raced:
                self.raced = True
                super().claim_folder(path)  # the competitor wins
            return super().claim_folder(path)

    backend = _Raced()

    key = archive_upload._reserve_folder(org.id, "bundle", backend)

    assert key == f"org_{org.id}/bundle (1)"
    assert {f"org_{org.id}/bundle/", f"org_{org.id}/bundle (1)/"} <= set(backend._objects)
    assert not any(in_transaction for _, in_transaction in backend.calls)


def test_reserve_folder_takes_a_name_the_store_keeps_refusing_as_a_conflict():
    # MinIO refuses a marker under a file at a parent path while the probe reports the
    # name free: this must not spin through every claim into a 503.
    class _RefusesEveryClaim(InMemoryStorageBackend):
        claims = 0

        def claim_folder(self, path):
            self.claims += 1
            return False

    backend = _RefusesEveryClaim()

    with pytest.raises(StoragePathIsFile) as caught:
        archive_upload._reserve_folder(7, "bundle", backend)
    assert caught.value.status_code == 409
    assert backend.claims == archive_upload._MAX_REFUSALS_OF_ONE_NAME
