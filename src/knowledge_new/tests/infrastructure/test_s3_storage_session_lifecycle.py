"""Each S3Storage operation must own and close its own client session.

The fake client models the strictest plausible library behaviour: using a client
whose session was closed raises. A manager that closes a shared client therefore
fails the second operation, and one that skips the close on error leaves a session
open.
"""

import asyncio

import pytest

from infrastructure.graphrag import storages
from infrastructure.graphrag.storages import S3Storage


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeMinio:
    instances: list["_FakeMinio"] = []
    objects: dict[str, bytes] = {}
    fail_put = False
    release_first_put: asyncio.Event | None = None

    def __init__(self, **kwargs) -> None:
        self.session_open = True
        _FakeMinio.instances.append(self)

    def _require_session(self) -> None:
        if not self.session_open:
            raise RuntimeError("session is closed")

    async def close_session(self) -> None:
        self.session_open = False

    async def bucket_exists(self, bucket_name: str) -> bool:
        self._require_session()
        return True

    async def put_object(self, bucket_name, object_name, data, length, content_type) -> None:
        self._require_session()
        if _FakeMinio.fail_put:
            raise RuntimeError("storage unavailable")
        if _FakeMinio.release_first_put is not None and object_name.endswith("slow.txt"):
            await _FakeMinio.release_first_put.wait()
            self._require_session()
        _FakeMinio.objects[object_name] = data.read()

    async def get_object(self, bucket_name, object_name) -> _FakeResponse:
        self._require_session()
        return _FakeResponse(_FakeMinio.objects[object_name])


@pytest.fixture(autouse=True)
def fake_minio(monkeypatch):
    _FakeMinio.instances = []
    _FakeMinio.objects = {}
    _FakeMinio.fail_put = False
    _FakeMinio.release_first_put = None
    monkeypatch.setattr(storages, "Minio", _FakeMinio)
    return _FakeMinio


@pytest.fixture
def storage() -> S3Storage:
    return S3Storage(
        endpoint="http://rustfs:9000",
        bucket="bucket",
        prefix="graphrag/rag_1",
        encoding="utf-8",
        access_key="key",
        secret_key="secret",
    )


async def test_successful_operation_leaves_storage_usable_for_the_next(storage):
    await storage.set("a.txt", "hello")

    assert await storage.get("a.txt") == "hello"


async def test_every_operation_closes_the_session_it_opened(storage, fake_minio):
    await storage.set("a.txt", "hello")
    await storage.get("a.txt")

    assert len(fake_minio.instances) == 2
    assert not any(client.session_open for client in fake_minio.instances)


async def test_failed_operation_closes_its_session_and_storage_stays_usable(storage, fake_minio):
    fake_minio.fail_put = True
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await storage.set("a.txt", "hello")

    assert not any(client.session_open for client in fake_minio.instances)

    fake_minio.fail_put = False
    await storage.set("a.txt", "hello")
    assert await storage.get("a.txt") == "hello"


async def test_concurrent_operations_do_not_close_each_others_session(storage, fake_minio):
    fake_minio.release_first_put = asyncio.Event()

    slow = asyncio.create_task(storage.set("slow.txt", "slow"))
    await asyncio.sleep(0)
    await storage.set("fast.txt", "fast")
    fake_minio.release_first_put.set()
    await slow

    assert fake_minio.objects.keys() == {
        "graphrag/rag_1/slow.txt",
        "graphrag/rag_1/fast.txt",
    }


async def test_early_return_paths_close_their_session(storage, fake_minio):
    async def missing(self, bucket_name, object_name):
        raise storages.S3Error("NoSuchKey", "missing", "", "", "", None)

    fake_minio.get_object = missing

    assert await storage.get("absent.txt") is None
    assert not any(client.session_open for client in fake_minio.instances)
