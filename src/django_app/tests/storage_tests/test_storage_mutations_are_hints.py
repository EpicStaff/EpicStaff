"""Storage mutations reported by a run are hints; the index only follows real storage state.

User code runs in the same process as `epicstaff_storage`, so it can forge the mutation
report. The handler therefore never deletes an object, drops a row only when the object is
really gone, and indexes a write only when the object exists.

Real InMemoryStorageBackend, real StorageFileSync, real DB.
"""

import json
from unittest import mock

import fakeredis
import pytest
from rbac.models import Organization
from tables.models import StorageFile
from tables.services import redis_pubsub, storage_service
from tables.services.storage_service.manager import StorageManager

from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return Organization.objects.create(name="Org StorageMutationHints")


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def pubsub(monkeypatch, backend):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    # close_old_connections would drop the test's transactional connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    monkeypatch.setattr(storage_service, "get_storage_manager", lambda: StorageManager(backend))
    return redis_pubsub.RedisPubSub()


def _report(pubsub, org, op, path):
    pubsub.storage_mutations_handler(
        {
            "data": json.dumps(
                {
                    "execution_id": "exec-1",
                    "org_prefix": f"org_{org.id}",
                    "session_id": None,
                    "mutations": [{"op": op, "path": f"org_{org.id}/{path}"}],
                }
            )
        }
    )


def _row(org, path, item_type="file"):
    return StorageFile.objects.create(
        org=org,
        path=path,
        name=path.rstrip("/").split("/")[-1],
        item_type=item_type,
        parent_path=path.rstrip("/").rsplit("/", 1)[0] + "/" if "/" in path.rstrip("/") else "",
    )


def _paths(org):
    return set(StorageFile.objects.filter(org=org).values_list("path", flat=True))


# ---- delete ----


def test_a_forged_delete_of_an_object_that_still_exists_keeps_its_row(pubsub, backend, org):
    backend.put_bytes(f"org_{org.id}/docs/keep.txt", b"data")
    _row(org, "docs/keep.txt")

    _report(pubsub, org, "delete", "docs/keep.txt")

    assert _paths(org) == {"docs/keep.txt"}
    assert f"org_{org.id}/docs/keep.txt" in backend._objects


def test_a_real_delete_removes_the_row(pubsub, backend, org):
    _row(org, "docs/gone.txt")

    _report(pubsub, org, "delete", "docs/gone.txt")

    assert _paths(org) == set()


def test_a_forged_folder_delete_with_objects_remaining_keeps_every_row(pubsub, backend, org):
    backend.put_bytes(f"org_{org.id}/docs/a.txt", b"data")
    _row(org, "docs/", item_type="folder")
    _row(org, "docs/a.txt")

    _report(pubsub, org, "delete", "docs/")
    _report(pubsub, org, "delete", "docs")

    assert _paths(org) == {"docs/", "docs/a.txt"}


def test_a_folder_delete_with_nothing_left_removes_the_folder_rows(pubsub, backend, org):
    _row(org, "docs/", item_type="folder")
    _row(org, "docs/a.txt")

    _report(pubsub, org, "delete", "docs")

    assert _paths(org) == set()


def test_a_forged_delete_of_a_folder_holding_only_a_keep_marker_keeps_its_rows(
    pubsub, backend, org
):
    backend.put_bytes(f"org_{org.id}/docs/.keep", b"")
    _row(org, "docs/", item_type="folder")

    _report(pubsub, org, "delete", "docs")

    assert _paths(org) == {"docs/"}


def test_a_forged_delete_of_a_folder_holding_only_a_nested_marker_keeps_its_rows(
    pubsub, backend, org
):
    backend.mkdir(f"org_{org.id}/docs/inner/")
    _row(org, "docs/", item_type="folder")
    _row(org, "docs/inner/", item_type="folder")

    _report(pubsub, org, "delete", "docs")

    assert _paths(org) == {"docs/", "docs/inner/"}


def test_an_unreachable_store_leaves_the_row(pubsub, backend, org):
    _row(org, "docs/a.txt")

    with mock.patch.object(backend, "head_file", side_effect=RuntimeError("storage unreachable")):
        _report(pubsub, org, "delete", "docs/a.txt")

    assert _paths(org) == {"docs/a.txt"}


# ---- write ----


def test_a_forged_write_of_a_missing_object_creates_no_row(pubsub, backend, org):
    _report(pubsub, org, "write", "docs/never-written.txt")

    assert _paths(org) == set()


@pytest.mark.parametrize("invalid_path", ["../outside.txt", "docs/bad\x00name.txt"])
def test_a_forged_write_of_an_invalid_path_creates_no_row(pubsub, backend, org, invalid_path):
    _report(pubsub, org, "write", invalid_path)

    assert _paths(org) == set()


def test_a_real_write_creates_a_row_with_the_stored_size(pubsub, backend, org):
    backend.put_bytes(f"org_{org.id}/docs/report.txt", b"12345")

    _report(pubsub, org, "write", "docs/report.txt")

    assert StorageFile.objects.get(org=org, path="docs/report.txt").size == 5


def test_an_unreachable_store_still_records_a_real_write_without_a_size(pubsub, backend, org):
    with mock.patch.object(backend, "head_file", side_effect=RuntimeError("storage unreachable")):
        _report(pubsub, org, "write", "docs/report.txt")

    assert StorageFile.objects.get(org=org, path="docs/report.txt").size is None
