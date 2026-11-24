"""Executable files written into storage by code never become indexed files.

User code can bypass `epicstaff_storage` with its own S3 client, so django enforces the
executable-extension block where a stored object would enter the file index: the
mutation handler and the reconciler refuse to index it. Neither deletes it: the
mutation report comes from code that can forge it.

Real InMemoryStorageBackend, real StorageFileSync, real DB.
"""

import json

import fakeredis
import pytest
from loguru import logger

from src.shared.epicstaff_storage.blocked_extensions import BLOCKED_EXTENSIONS
from tables.models import StorageFile
from tables.services import redis_pubsub, storage_service
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.reconciler import StorageReconciler
from tables.validators.file_upload_validator import FileValidator
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db


def test_the_library_copy_of_the_blocked_extensions_matches_the_validator():
    assert BLOCKED_EXTENSIONS == FileValidator.BLOCKED_EXTENSIONS


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def pubsub(monkeypatch, backend, redis_client):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: redis_client
    )
    # close_old_connections would drop the test's transactional connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    monkeypatch.setattr(storage_service, "get_storage_manager", lambda: StorageManager(backend))
    return redis_pubsub.RedisPubSub()


@pytest.fixture
def warnings():
    messages = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


def _message(org, *writes, session_id=None):
    return {
        "data": json.dumps(
            {
                "execution_id": "exec-1",
                "org_prefix": f"org_{org.id}",
                "session_id": session_id,
                "mutations": [{"op": "write", "path": f"org_{org.id}/{path}"} for path in writes],
            }
        )
    }


def _paths(org):
    return set(StorageFile.objects.filter(org=org, item_type="file").values_list("path", flat=True))


class TestMutationHandler:
    @pytest.mark.parametrize("name", ["payload.exe", "PAYLOAD.EXE", "out/run.CoMmAnD", "x/lib.so"])
    def test_an_executable_write_is_never_recorded_and_never_deleted(
        self, pubsub, backend, org, warnings, name
    ):
        backend.put_bytes(f"org_{org.id}/{name}", b"MZ")

        pubsub.storage_mutations_handler(_message(org, name))

        # A forged report must not make django delete anything.
        assert f"org_{org.id}/{name}" in backend._objects
        assert not StorageFile.objects.filter(org=org).exists()
        logged = "".join(warnings)
        assert name in logged
        assert str(org.id) in logged

    def test_other_writes_in_the_batch_are_still_recorded(self, pubsub, backend, org):
        backend.put_bytes(f"org_{org.id}/bad.sh", b"#!/bin/sh")
        backend.put_bytes(f"org_{org.id}/notes.txt", b"hello")
        backend.put_bytes(f"org_{org.id}/archive.exe.txt", b"hi")

        pubsub.storage_mutations_handler(_message(org, "bad.sh", "notes.txt", "archive.exe.txt"))

        assert _paths(org) == {"notes.txt", "archive.exe.txt"}
        assert f"org_{org.id}/bad.sh" in backend._objects

    def test_an_executable_is_not_tracked_in_the_session_write_set(
        self, pubsub, backend, redis_client, org
    ):
        backend.put_bytes(f"org_{org.id}/bad.exe", b"MZ")
        backend.put_bytes(f"org_{org.id}/ok.txt", b"hello")

        pubsub.storage_mutations_handler(_message(org, "bad.exe", "ok.txt", session_id=7))

        assert redis_client.smembers("session:7:storage_mutations") == {f"{org.id}:ok.txt"}


class TestReconciler:
    def test_executable_objects_are_not_indexed_and_not_deleted(self, org, backend, warnings):
        backend.put_bytes(f"org_{org.id}/docs/ok.txt", b"hello")
        backend.put_bytes(f"org_{org.id}/docs/bad.EXE", b"MZ")
        backend.put_bytes(f"org_{org.id}/only/bad.sh", b"#!/bin/sh")

        StorageReconciler(backend).reconcile_tree(org.id, "")

        assert _paths(org) == {"docs/ok.txt"}
        # A folder holding nothing but executables is not created either.
        assert not StorageFile.objects.filter(org=org, path="only/").exists()
        assert f"org_{org.id}/docs/bad.EXE" in backend._objects
        assert f"org_{org.id}/only/bad.sh" in backend._objects
        assert "docs/bad.EXE" in "".join(warnings)

    def test_skipped_executables_are_reported_in_one_warning_with_a_count(
        self, org, backend, warnings
    ):
        for index in range(40):
            backend.put_bytes(f"org_{org.id}/bin/tool-{index}.exe", b"MZ")

        StorageReconciler(backend).reconcile_tree(org.id, "")

        about_executables = [message for message in warnings if "executable" in message]
        assert len(about_executables) == 1
        assert "40 executable object(s)" in about_executables[0]
        assert about_executables[0].count(".exe") < 40

    def test_an_existing_row_for_an_executable_is_swept(self, org, backend):
        StorageFile.objects.create(org=org, path="bad.exe", name="bad.exe", item_type="file")
        backend.put_bytes(f"org_{org.id}/bad.exe", b"MZ")

        StorageReconciler(backend).reconcile_tree(org.id, "")

        assert not StorageFile.objects.filter(org=org, path="bad.exe").exists()
        assert f"org_{org.id}/bad.exe" in backend._objects
