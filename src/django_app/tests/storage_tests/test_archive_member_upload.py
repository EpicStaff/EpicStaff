"""ArchiveMemberUploader leaves nothing it wrote behind when it fails, and takes
back exactly its own keys: never a neighbour that shares the folder's name."""

import io

import pytest

from tables.services.storage_service.archive_unpacking.extraction_guard import (
    ArchiveExtractionGuard,
    ArchiveLimitExceeded,
)
from tables.services.storage_service.upload.archive_members import (
    ArchiveMemberUploader,
    _ReplayingReader,
)
from tables.services.storage_service.base import StorageUnreachable
from tests.storage_tests.in_memory_backend import (
    FailingInMemoryBackend,
    InMemoryStorageBackend,
    zip_bytes,
)
from utils.logger import logger

FOLDER = "org_1/report"


def _upload(backend, members: dict[str, bytes], *, guard=None, workers=2):
    guard = guard or ArchiveExtractionGuard(max_entries=100, max_total_bytes=10_000)
    return ArchiveMemberUploader(backend, FOLDER, guard, workers=workers).upload(
        io.BytesIO(zip_bytes(members))
    )


def _keys_under_folder(backend) -> list[str]:
    return [key for key in backend._objects if key.startswith(FOLDER + "/")]


def test_small_members_go_through_the_put_pool_and_big_ones_stream():
    # part_size 4: "tiny" goes through the PUT pool, "big.bin" through upload_stream
    backend = InMemoryStorageBackend(part_size=4)
    members = {f"sub/s{index}.txt": b"tiny" for index in range(5)} | {"big.bin": b"0123456789"}

    sizes = _upload(backend, members)

    assert sizes == {name: len(data) for name, data in members.items()}
    assert {key: backend._objects[key][0] for key in _keys_under_folder(backend)} == {
        f"{FOLDER}/{name}": data for name, data in members.items()
    }


@pytest.mark.parametrize(
    ("failing_key", "part_size"), [("c.txt", 1024), ("z.txt", 4)], ids=["put", "streamed"]
)
def test_a_failed_write_takes_back_the_members_but_no_neighbour_sharing_the_name(
    failing_key, part_size
):
    # A file whose key starts like the folder's and another upload's file inside
    # the folder are not this call's to delete.
    backend = FailingInMemoryBackend(f"{FOLDER}/{failing_key}", part_size=part_size)
    backend.put_bytes(f"{FOLDER}.txt", b"the user's own file named like the folder")
    backend.put_bytes(f"{FOLDER}/other.txt", b"written by another upload")
    members = {"big.bin": b"0123456789", "a.txt": b"a", "c.txt": b"c", "z.txt": b"z"}

    with pytest.raises(StorageUnreachable):
        _upload(backend, members)

    assert _keys_under_folder(backend) == [f"{FOLDER}/other.txt"]
    assert backend._objects[f"{FOLDER}.txt"][0] == b"the user's own file named like the folder"


def test_a_limit_hit_mid_archive_takes_back_the_members_already_written():
    backend = InMemoryStorageBackend()
    guard = ArchiveExtractionGuard(max_entries=100, max_total_bytes=10)

    with pytest.raises(ArchiveLimitExceeded):
        _upload(backend, {"a.txt": b"x" * 6, "b.txt": b"y" * 6}, guard=guard)

    assert _keys_under_folder(backend) == []


def test_a_failing_cleanup_is_logged_and_the_original_error_still_raised():
    backend = FailingInMemoryBackend(f"{FOLDER}/b.txt")

    def _delete_fails(_keys):
        raise RuntimeError("delete failed too")

    backend.delete_keys = _delete_fails
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="ERROR")
    try:
        with pytest.raises(StorageUnreachable):
            _upload(backend, {"a.txt": b"a", "b.txt": b"b"})
    finally:
        logger.remove(sink_id)

    assert any("Could not remove" in message for message in messages)


def test_a_streamed_member_fills_every_read_until_eof():
    # one multipart part per read(): a short read mid-stream would be a part under
    # the S3 minimum and fail CompleteMultipartUpload
    class _Trickle(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3) if size and size > 0 else size)

    reader = _ReplayingReader(b"0123456789A", _Trickle(b"B" * 25))
    sizes = []
    while chunk := reader.read(8):
        sizes.append(len(chunk))

    assert sizes == [8, 8, 8, 8, 4]
    assert reader.bytes_read == 36
