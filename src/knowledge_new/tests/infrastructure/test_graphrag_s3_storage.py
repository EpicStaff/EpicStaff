"""graphrag's S3 storage and the artifact store over a knowledge bucket.

The bucket is an in-memory stand-in for foundation's `S3Bucket`; foundation's own
suite covers the wire protocol against a real RustFS.
"""

import io
import re

import pytest
from domain.errors import ArtifactStorageError
from infrastructure.graphrag import storages
from infrastructure.graphrag.artifact_store import S3ArtifactStore
from infrastructure.graphrag.s3_bucket import parse_endpoint
from infrastructure.graphrag.storages import S3Storage

from tests.fakes.s3_bucket import InMemoryS3Bucket


@pytest.fixture
def bucket(monkeypatch):
    bucket = InMemoryS3Bucket()
    monkeypatch.setattr(storages, "open_bucket", lambda *args: bucket)
    return bucket


@pytest.fixture
def storage(bucket):
    return S3Storage(
        endpoint="http://storage:9000",
        bucket="knowledge",
        prefix="graphrag/rag_1/a",
        encoding="utf-8",
        access_key="key",
        secret_key="secret",
    )


async def test_set_then_get_round_trips_text_and_bytes(storage):
    await storage.set("output/notes.txt", "hello")
    await storage.set("output/data.bin", b"\x00\x01")

    assert await storage.get("output/notes.txt") == "hello"
    assert await storage.get("output/data.bin", as_bytes=True) == b"\x00\x01"


async def test_get_of_a_missing_key_is_none(storage):
    assert await storage.get("missing.txt") is None


async def test_has_and_delete(storage):
    await storage.set("a.txt", "x")
    assert await storage.has("a.txt") is True

    await storage.delete("a.txt")

    assert await storage.has("a.txt") is False


async def test_keys_and_find_stay_inside_the_prefix(storage, bucket):
    await storage.set("output/entities.parquet", b"1")
    await storage.set("cache/x.json", b"2")
    bucket.objects_by_key["graphrag/rag_1/b/output/entities.parquet"] = b"other slot"

    assert sorted(storage.keys()) == ["cache/x.json", "output/entities.parquet"]
    assert list(storage.find(re.compile(r"\.parquet$"))) == ["output/entities.parquet"]


async def test_clear_deletes_only_the_prefix(storage, bucket):
    await storage.set("a.txt", "x")
    bucket.objects_by_key["graphrag/rag_1/b/a.txt"] = b"other slot"

    await storage.clear()

    assert list(bucket.objects_by_key) == ["graphrag/rag_1/b/a.txt"]


async def test_child_writes_under_a_nested_prefix(storage, bucket):
    await storage.child("output").set("a.txt", "x")

    assert list(bucket.objects_by_key) == ["graphrag/rag_1/a/output/a.txt"]


async def test_creation_date_of_a_missing_key_is_empty(storage):
    assert await storage.get_creation_date("missing.txt") == ""


async def test_creation_date_of_a_stored_key_is_formatted(storage):
    await storage.set("a.txt", "x")

    assert (await storage.get_creation_date("a.txt")).startswith("2024-01-01")


async def test_artifact_store_lists_with_sizes_and_streams_objects():
    bucket = InMemoryS3Bucket()
    store = S3ArtifactStore(bucket)
    await store.put("graphrag/rag_1/a/x.bin", io.BytesIO(b"abcdef"), 6)

    listed = await store.list_objects("graphrag/rag_1/")
    chunks = [chunk async for chunk in store.iter_object("graphrag/rag_1/a/x.bin")]

    assert [(stored.key, stored.size) for stored in listed] == [("graphrag/rag_1/a/x.bin", 6)]
    assert b"".join(chunks) == b"abcdef"


async def test_artifact_store_clear_reports_a_refused_delete():
    bucket = InMemoryS3Bucket()
    bucket.objects_by_key["graphrag/rag_1/a/x.bin"] = b"x"
    bucket.refused_keys.add("graphrag/rag_1/a/x.bin")

    with pytest.raises(ArtifactStorageError):
        await S3ArtifactStore(bucket).clear("graphrag/rag_1/")


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://storage:9000", (False, "storage", 9000)),
        ("https://s3.example.com:443", (True, "s3.example.com", 443)),
    ],
)
def test_parse_endpoint(endpoint, expected):
    assert parse_endpoint(endpoint) == expected


@pytest.mark.parametrize("endpoint", ["storage:9000", "ftp://storage:21", "http://storage"])
def test_parse_endpoint_rejects_what_is_not_an_http_url_with_a_port(endpoint):
    with pytest.raises(ValueError):
        parse_endpoint(endpoint)
