"""
Every writer other than the streaming upload must record real sizes and respect
the org storage quota: copy, cross-org copy/move (hard 413) and agent/sandbox
writes (recorded at their stored size, over quota only logged).

Real InMemoryStorageBackend, real StorageFileSync and the quota module, real DB.
"""

import json

import fakeredis
import pytest
from django.test import override_settings
from loguru import logger

from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services import redis_pubsub
from tables.services import storage_service
from tables.services.storage_service import manager as manager_module
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.quota import org_used_bytes
from tables.views import storage_views
from tests.storage_tests.in_memory_backend import (
    FakeS3Client,
    InMemoryStorageBackend,
    client_error,
    make_s3_backend,
    seed_file,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def manager(backend):
    return StorageManager(backend)


@pytest.fixture
def skip_early_quota_reject(monkeypatch):
    """Let the unlocked pre-check pass, as when a concurrent write fills the org
    between the pre-check and the locked row write; the locked check still runs."""
    monkeypatch.setattr(manager_module, "ensure_fits_quota", lambda *args, **kwargs: None)


def _row_sizes(org):
    return dict(
        StorageFile.objects.filter(org=org, item_type="file").values_list("path", "size")
    )


def _object_keys(backend):
    return set(backend._objects)


class TestCopy:
    def test_copy_records_the_source_size(self, manager, org):
        seed_file(manager._backend, org.id, "a.txt", b"0123456789")

        manager.copy(org.id, "a.txt", "")

        assert _row_sizes(org) == {"a.txt": 10, "a (1).txt": 10}
        assert org_used_bytes(org.id) == 20

    def test_folder_copy_records_every_nested_size(self, manager, org):
        seed_file(manager._backend, org.id, "docs/a.txt", b"abc")
        seed_file(manager._backend, org.id, "docs/sub/b.txt", b"hello")
        manager.mkdir(org.id, "docs/empty")

        manager.copy(org.id, "docs", "")

        sizes = _row_sizes(org)
        assert sizes["docs (1)/a.txt"] == 3
        assert sizes["docs (1)/sub/b.txt"] == 5
        assert StorageFile.objects.filter(
            org=org, path="docs (1)/empty/", item_type="folder"
        ).exists()
        assert org_used_bytes(org.id) == 16

    @override_settings(ORG_STORAGE_QUOTA=35)
    def test_repeated_copies_count_against_the_quota(self, manager, org):
        seed_file(manager._backend, org.id, "a.txt", b"0123456789")
        manager.copy(org.id, "a.txt", "")
        manager.copy(org.id, "a.txt", "")
        assert org_used_bytes(org.id) == 30

        with pytest.raises(StorageQuotaExceeded):
            manager.copy(org.id, "a.txt", "")

        assert org_used_bytes(org.id) == 30

    @override_settings(ORG_STORAGE_QUOTA=15)
    def test_copy_over_quota_is_rejected_before_copying(self, manager, backend, org):
        seed_file(manager._backend, org.id, "a.txt", b"0123456789")
        keys_before = _object_keys(backend)

        with pytest.raises(StorageQuotaExceeded):
            manager.copy(org.id, "a.txt", "")

        assert _object_keys(backend) == keys_before
        assert _row_sizes(org) == {"a.txt": 10}

    def test_copy_api_over_quota_returns_413(self, auth_client, default_org, manager, monkeypatch):
        seed_file(manager._backend, default_org.id, "a.txt", b"0123456789")
        monkeypatch.setattr(storage_views, "get_storage_manager", lambda: manager)

        with override_settings(ORG_STORAGE_QUOTA=15):
            # "/" is the root: the serializer normalizes it to "".
            response = auth_client.post(
                "/api/storage/copy/", {"from_path": "a.txt", "to_path": "/"}, format="json"
            )

        assert response.status_code == 413
        assert response.json()["code"] == "storage_quota_exceeded"
        assert _row_sizes(default_org) == {"a.txt": 10}

    def test_copy_api_within_quota_copies_to_the_root(
        self, auth_client, default_org, manager, monkeypatch
    ):
        seed_file(manager._backend, default_org.id, "a.txt", b"0123456789")
        monkeypatch.setattr(storage_views, "get_storage_manager", lambda: manager)

        response = auth_client.post(
            "/api/storage/copy/", {"from_path": "a.txt", "to_path": "/"}, format="json"
        )

        assert response.status_code == 200
        assert _row_sizes(default_org) == {"a.txt": 10, "a (1).txt": 10}

    @override_settings(ORG_STORAGE_QUOTA=15)
    def test_files_without_a_recorded_size_are_counted_at_their_stored_size(
        self, manager, backend, org
    ):
        # A row from before sizes were tracked: the object has 10 bytes, the row none.
        backend.put_bytes(f"org_{org.id}/legacy.bin", b"0123456789")
        StorageFileSync.on_upload(org.id, "legacy.bin")

        manager.copy(org.id, "legacy.bin", "")
        assert _row_sizes(org) == {"legacy.bin": None, "legacy (1).bin": 10}

        with pytest.raises(StorageQuotaExceeded):
            manager.copy(org.id, "legacy.bin", "")
        assert org_used_bytes(org.id) == 10

    @override_settings(ORG_STORAGE_QUOTA=15)
    def test_over_quota_rollback_removes_the_copies_in_one_batch(
        self, org, skip_early_quota_reject
    ):
        client = FakeS3Client()
        client.objects.update(
            {f"org_{org.id}/docs/a.txt": b"abcdefgh", f"org_{org.id}/docs/b.txt": b"12345678"}
        )
        objects_before = dict(client.objects)
        manager = StorageManager(make_s3_backend(client))

        with pytest.raises(StorageQuotaExceeded):
            manager.copy(org.id, "docs", "")

        assert client.objects == objects_before
        assert client.delete_batches == [
            [f"org_{org.id}/docs (1)/a.txt", f"org_{org.id}/docs (1)/b.txt"]
        ]
        assert not StorageFile.objects.filter(org=org).exists()


class TestCrossOrg:
    @override_settings(ORG_STORAGE_QUOTA=15)
    @pytest.mark.parametrize("operation", ["copy_cross_org", "move_cross_org"])
    def test_cross_org_writes_over_the_destination_quota_leave_both_orgs_untouched(
        self, manager, backend, org, second_org, operation
    ):
        seed_file(manager._backend, org.id, "a.txt", b"0123456789")
        seed_file(manager._backend, second_org.id, "full.txt", b"0123456789")
        keys_before = _object_keys(backend)

        with pytest.raises(StorageQuotaExceeded):
            getattr(manager, operation)(org.id, "a.txt", second_org.id, "")

        assert _object_keys(backend) == keys_before
        assert _row_sizes(org) == {"a.txt": 10}
        assert _row_sizes(second_org) == {"full.txt": 10}

    def test_cross_org_move_records_nested_sizes_and_removes_the_source(
        self, manager, backend, org, second_org
    ):
        seed_file(manager._backend, org.id, "docs/a.txt", b"abc")
        seed_file(manager._backend, org.id, "docs/sub/b.txt", b"hello")
        manager.mkdir(second_org.id, "inbox")

        manager.move_cross_org(org.id, "docs", second_org.id, "inbox")

        assert _row_sizes(second_org) == {"inbox/docs/a.txt": 3, "inbox/docs/sub/b.txt": 5}
        assert org_used_bytes(second_org.id) == 8
        assert not StorageFile.objects.filter(org=org).exists()
        assert not any(key.startswith(f"org_{org.id}/") for key in backend._objects)

    @override_settings(ORG_STORAGE_QUOTA=15)
    def test_cross_org_move_rejected_under_the_lock_keeps_the_source(
        self, manager, backend, org, second_org, skip_early_quota_reject
    ):
        seed_file(manager._backend, org.id, "docs/a.txt", b"abcdefgh")
        seed_file(manager._backend, second_org.id, "full.txt", b"0123456789")
        keys_before = _object_keys(backend)

        with pytest.raises(StorageQuotaExceeded):
            manager.move_cross_org(org.id, "docs", second_org.id, "")

        assert _object_keys(backend) == keys_before
        assert _row_sizes(org) == {"docs/a.txt": 8}
        assert _row_sizes(second_org) == {"full.txt": 10}


class _NoRedis:
    """Enough of a Redis client for RedisPubSub.__init__; events without a
    session_id never touch it."""

    def pubsub(self):
        return object()


class TestAgentWrites:
    @pytest.fixture
    def pubsub(self, monkeypatch, manager):
        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _NoRedis()
        )
        # close_old_connections would drop the test's transactional connection.
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        monkeypatch.setattr(storage_service, "get_storage_manager", lambda: manager)
        return redis_pubsub.RedisPubSub()

    @pytest.fixture
    def warnings(self):
        messages = []
        sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
        yield messages
        logger.remove(sink_id)

    @staticmethod
    def _mutation_message(org, *writes):
        return {
            "data": json.dumps(
                {
                    "execution_id": "exec-1",
                    "org_prefix": f"org_{org.id}",
                    "mutations": [
                        {"op": "write", "path": f"org_{org.id}/{path}"} for path in writes
                    ],
                }
            )
        }

    def test_write_records_the_stored_size(self, pubsub, backend, org):
        backend.put_bytes(f"org_{org.id}/out/report.txt", b"12345")

        pubsub.storage_mutations_handler(self._mutation_message(org, "out/report.txt"))

        row = StorageFile.objects.get(org=org, path="out/report.txt")
        assert row.size == 5
        assert row.s3_modified is not None
        assert StorageFile.objects.filter(org=org, path="out/", item_type="folder").exists()
        assert org_used_bytes(org.id) == 5

    def test_overwrite_updates_the_recorded_size(self, pubsub, backend, manager, org):
        seed_file(manager._backend, org.id, "report.txt", b"12")
        backend.put_bytes(f"org_{org.id}/report.txt", b"1234567")

        pubsub.storage_mutations_handler(self._mutation_message(org, "report.txt"))

        assert _row_sizes(org) == {"report.txt": 7}

    @override_settings(ORG_STORAGE_QUOTA=3)
    def test_write_over_quota_is_recorded_and_only_warned(self, pubsub, backend, org, warnings):
        backend.put_bytes(f"org_{org.id}/big.bin", b"12345")

        pubsub.storage_mutations_handler(self._mutation_message(org, "big.bin"))

        assert _row_sizes(org) == {"big.bin": 5}
        assert any("over its storage quota" in message for message in warnings)

    def test_missing_object_is_skipped_and_the_rest_recorded(
        self, pubsub, backend, org, warnings
    ):
        backend.put_bytes(f"org_{org.id}/kept.txt", b"abc")

        pubsub.storage_mutations_handler(self._mutation_message(org, "gone.txt", "kept.txt"))

        assert _row_sizes(org) == {"kept.txt": 3}
        assert any("gone.txt" in message for message in warnings)

    def test_a_malformed_org_prefix_is_logged_and_nothing_is_recorded(
        self, pubsub, org, warnings
    ):
        message = {
            "data": json.dumps(
                {
                    "execution_id": "exec-1",
                    "org_prefix": "orgless",
                    "mutations": [{"op": "write", "path": "orgless/a.txt"}],
                }
            )
        }

        pubsub.storage_mutations_handler(message)

        assert "Invalid org_prefix format: orgless" in "".join(warnings)
        assert not StorageFile.objects.filter(org=org).exists()

    def test_an_unreadable_event_is_logged_with_its_error(self, pubsub, warnings):
        pubsub.storage_mutations_handler({"data": json.dumps({"org_prefix": "org_1"})})

        assert "Error handling storage_mutations message: " in "".join(warnings)

    @pytest.fixture
    def session_pubsub(self, monkeypatch):
        """A handler whose backend fails for chosen paths, on a fake Redis, so the
        session bookkeeping can be checked too."""
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        backend = _FailingHeadBackend()
        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: redis_client
        )
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        monkeypatch.setattr(storage_service, "get_storage_manager", lambda: StorageManager(backend))
        return redis_pubsub.RedisPubSub(), backend, redis_client

    @staticmethod
    def _session_message(org, session_id, *mutations):
        return {
            "data": json.dumps(
                {
                    "execution_id": "exec-1",
                    "org_prefix": f"org_{org.id}",
                    "session_id": session_id,
                    "mutations": [
                        {"op": op, "path": f"org_{org.id}/{path}"} for op, path in mutations
                    ],
                }
            )
        }

    @pytest.mark.parametrize(
        "storage_error",
        [
            client_error("InternalError", 500, "HeadObject"),
            RuntimeError("read timeout"),
        ],
        ids=["storage-5xx", "any-error"],
    )
    def test_a_failing_size_lookup_keeps_the_row_the_rest_and_the_session_set(
        self, session_pubsub, org, storage_error
    ):
        pubsub, backend, redis_client = session_pubsub
        backend.put_bytes(f"org_{org.id}/before.txt", b"abc")
        backend.put_bytes(f"org_{org.id}/broken.txt", b"12345")
        backend.put_bytes(f"org_{org.id}/after.txt", b"hello!")
        StorageFileSync.on_upload(org.id, "old.txt", size=4)
        redis_client.sadd("session:7:storage_mutations", f"{org.id}:old.txt")
        backend.failures[f"org_{org.id}/broken.txt"] = storage_error

        pubsub.storage_mutations_handler(
            self._session_message(
                org,
                7,
                ("write", "before.txt"),
                ("write", "broken.txt"),
                ("write", "after.txt"),
                ("delete", "old.txt"),
            )
        )

        assert _row_sizes(org) == {"before.txt": 3, "broken.txt": None, "after.txt": 6}
        assert redis_client.smembers("session:7:storage_mutations") == {
            f"{org.id}:before.txt",
            f"{org.id}:broken.txt",
            f"{org.id}:after.txt",
        }

    def test_a_write_without_a_session_is_recorded_and_touches_no_session_set(
        self, session_pubsub, org
    ):
        # A test-mode run has no session: its writes land in the browser index
        # but belong to no session's output files.
        pubsub, backend, redis_client = session_pubsub
        backend.put_bytes(f"org_{org.id}/test-runs/python_node-5/out.txt", b"abc")

        pubsub.storage_mutations_handler(
            self._session_message(org, None, ("write", "test-runs/python_node-5/out.txt"))
        )

        assert _row_sizes(org) == {"test-runs/python_node-5/out.txt": 3}
        assert redis_client.keys("session:*") == []

    def test_a_failing_row_write_does_not_drop_the_rest(self, session_pubsub, org, monkeypatch):
        pubsub, backend, redis_client = session_pubsub
        backend.put_bytes(f"org_{org.id}/kept.txt", b"abc")
        StorageFileSync.on_upload(org.id, "old.txt", size=4)
        real_on_upload = StorageFileSync.on_upload

        def _on_upload(org_id, path, *args, **kwargs):
            if path == "broken.txt":
                raise RuntimeError("database hiccup")
            return real_on_upload(org_id, path, *args, **kwargs)

        backend.put_bytes(f"org_{org.id}/broken.txt", b"12345")
        monkeypatch.setattr(StorageFileSync, "on_upload", staticmethod(_on_upload))

        pubsub.storage_mutations_handler(
            self._session_message(
                org, 7, ("write", "broken.txt"), ("write", "kept.txt"), ("delete", "old.txt")
            )
        )

        assert _row_sizes(org) == {"kept.txt": 3}
        assert redis_client.smembers("session:7:storage_mutations") == {
            f"{org.id}:broken.txt",
            f"{org.id}:kept.txt",
        }


class _FailingHeadBackend(InMemoryStorageBackend):
    """In-memory storage whose size lookup raises the error mapped to a key."""

    def __init__(self):
        super().__init__(organization_prefix="")
        self.failures: dict[str, BaseException] = {}

    def head_file(self, path):
        if path in self.failures:
            raise self.failures[path]
        return super().head_file(path)
