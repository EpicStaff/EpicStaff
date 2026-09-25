"""upload_archive_members leaves nothing it wrote behind when it fails, and takes
back exactly its own keys: never a neighbour that shares the folder's name."""

import io
import zipfile

import pytest

from tables.services.storage_service.archive_limits import (
    ArchiveExtractionGuard,
    ArchiveLimitExceeded,
)
from tables.services.storage_service.archive_member_upload import upload_archive_members
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from utils.logger import logger

FOLDER = "org_1/report"


def _zip(members: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


class _StoreFailingOn(InMemoryStorageBackend):
    """Object store double that refuses one key, as MinIO would on an outage."""

    def __init__(self, failing_key: str):
        super().__init__()
        self.failing_key = failing_key

    def put_bytes(self, path: str, data: bytes) -> int:
        if path == self.failing_key:
            raise ConnectionError("minio went away")
        return super().put_bytes(path, data)

    def upload_stream(self, path: str, file_object, *, part_size: int) -> None:
        if path == self.failing_key:
            raise ConnectionError("minio went away")
        super().upload_stream(path, file_object, part_size=part_size)


def _upload(backend, archive, *, guard=None, part_size=1024, workers=2):
    guard = guard or ArchiveExtractionGuard(max_entries=100, max_total_bytes=10_000)
    return upload_archive_members(
        archive, guard, backend, FOLDER, part_size=part_size, workers=workers
    )


def _keys_under_folder(backend) -> list[str]:
    return [key for key in backend._objects if key.startswith(FOLDER + "/")]


def test_returns_the_sizes_and_keeps_every_member():
    backend = InMemoryStorageBackend()
    sizes = _upload(backend, _zip({"a.txt": b"aa", "sub/b.txt": b"bbb"}))
    assert sizes == {"a.txt": 2, "sub/b.txt": 3}
    assert sorted(_keys_under_folder(backend)) == [f"{FOLDER}/a.txt", f"{FOLDER}/sub/b.txt"]


def test_a_failed_put_takes_back_the_members_but_no_neighbour_sharing_the_name():
    # MinIO never holds a file at FOLDER itself (nothing could be written under it),
    # but a file whose key starts like the folder's and another upload's file inside
    # the folder are not this call's to delete.
    backend = _StoreFailingOn(f"{FOLDER}/c.txt")
    backend.put_bytes(f"{FOLDER}.txt", b"the user's own file named like the folder")
    backend.put_bytes(f"{FOLDER}/other.txt", b"written by another upload")

    with pytest.raises(ConnectionError, match="minio went away"):
        _upload(backend, _zip({"a.txt": b"a", "b.txt": b"b", "c.txt": b"c", "d.txt": b"d"}))

    assert _keys_under_folder(backend) == [f"{FOLDER}/other.txt"]
    assert backend._objects[f"{FOLDER}.txt"][0] == b"the user's own file named like the folder"


def test_a_limit_hit_mid_archive_takes_back_the_members_already_written():
    backend = InMemoryStorageBackend()
    guard = ArchiveExtractionGuard(max_entries=100, max_total_bytes=10)

    with pytest.raises(ArchiveLimitExceeded):
        _upload(backend, _zip({"a.txt": b"x" * 6, "b.txt": b"y" * 6}), guard=guard)

    assert _keys_under_folder(backend) == []


def test_a_streamed_member_is_taken_back_too():
    # part_size 4: "big.bin" goes through upload_stream, not the PUT pool
    backend = _StoreFailingOn(f"{FOLDER}/z.txt")
    archive = _zip({"big.bin": b"0123456789", "z.txt": b"z"})

    with pytest.raises(ConnectionError):
        _upload(backend, archive, part_size=4)

    assert _keys_under_folder(backend) == []


def test_a_failing_cleanup_is_logged_and_the_original_error_still_raised():
    backend = _StoreFailingOn(f"{FOLDER}/b.txt")

    def _delete_fails(_keys):
        raise RuntimeError("delete failed too")

    backend.delete_keys = _delete_fails
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="ERROR")
    try:
        with pytest.raises(ConnectionError, match="minio went away"):
            _upload(backend, _zip({"a.txt": b"a", "b.txt": b"b"}))
    finally:
        logger.remove(sink_id)

    assert any("Could not remove" in message for message in messages)
