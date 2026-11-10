"""When a run ends, what its code left under the folders it was granted joins the file index.

Python code can write with no report at all (boto3 direct), so before a run's account is
revoked the granted folders are reconciled from storage itself. That makes the files visible
and their bytes count toward the org's quota. A reconcile failure never blocks the revocation.

Real services and database, in-memory storage backend, fake storage admin API.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from storage_credentials.models import TemporaryStorageAccount
from datetime import timedelta

from django.utils import timezone
from storage_credentials.services import run_bin_purge as run_bin_purge_module
from storage_credentials.services import session_credential_service as service_module
from tables.services.storage_service.manager import StorageManager
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import PythonCodeResult, StorageFile
from tables.services.storage_service.quota import org_used_bytes

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import (
    GATEWAY_PATH,
    ORG_CREDENTIALS_PATH,
    FakeStorageGateway,
)
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

OWN_FOLDER = "test-runs/function-1/"


@pytest.fixture(autouse=True)
def _bucket(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"
    settings.ORG_STORAGE_QUOTA = 10**9


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(
            ORG_CREDENTIALS_PATH,
            return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
        ),
    ):
        yield fake


@pytest.fixture
def backend(monkeypatch):
    in_memory = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(service_module, "get_storage_backend", lambda organization_prefix="": in_memory)
    manager = StorageManager(in_memory)
    monkeypatch.setattr(run_bin_purge_module, "get_storage_manager", lambda: manager)
    return in_memory


def _start(org, user, shared_paths=()) -> str:
    """Mint a test run's account over the run folder and `shared_paths`; returns the execution id."""
    result = PythonCodeResult.objects.create(
        execution_id="exec-end", org_id=org.id, status=PythonCodeResult.Status.COMPLETED
    )
    session_credential_service.issue_for_test_run(
        result,
        [OWN_FOLDER, *shared_paths],
        org.id,
        own_paths=[OWN_FOLDER],
        acting_identity=ActingIdentity.for_request(user, None),
    )
    return result.execution_id


def _store(backend, org, path: str, size: int) -> None:
    backend.put_bytes(f"org_{org.id}/{path}", b"x" * size)


def _indexed(org) -> dict[str, int | None]:
    return {
        row.path: row.size for row in StorageFile.objects.filter(org=org, item_type="file")
    }


def test_an_object_written_without_any_report_is_indexed_and_counted_when_the_run_ends(
    gateway, backend, acme, member_only
):
    execution_id = _start(acme, member_only)
    _store(backend, acme, f"{OWN_FOLDER}sneaky.bin", 25)

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {f"{OWN_FOLDER}sneaky.bin": 25}
    assert org_used_bytes(acme.id) == 25
    assert not TemporaryStorageAccount.objects.exists()
    assert len(gateway.deleted) == 1


def test_a_granted_shared_folder_and_a_granted_single_file_are_synced_too(
    gateway, backend, acme, member_only
):
    execution_id = _start(acme, member_only, shared_paths=["reports/", "notes/todo.txt"])
    _store(backend, acme, "reports/new.csv", 7)
    _store(backend, acme, "notes/todo.txt", 3)
    _store(backend, acme, "notes/todo.txt.bak", 9)

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {"reports/new.csv": 7, "notes/todo.txt": 3}


def test_objects_outside_the_granted_folders_are_not_indexed(gateway, backend, acme, member_only):
    execution_id = _start(acme, member_only)
    _store(backend, acme, "elsewhere/other.bin", 40)

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {}


def test_an_executable_left_in_a_granted_folder_stays_unindexed(gateway, backend, acme, member_only):
    execution_id = _start(acme, member_only)
    _store(backend, acme, f"{OWN_FOLDER}payload.sh", 10)
    _store(backend, acme, f"{OWN_FOLDER}data.txt", 5)

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {f"{OWN_FOLDER}data.txt": 5}


def test_the_sync_never_drops_a_row_for_an_object_missing_from_the_listing(
    gateway, backend, acme, member_only
):
    """Another upload may have created the row after the listing was taken; sweeping would
    make a live file vanish from the index and the quota. A row left behind by an
    unreported delete overcounts until the manual reconcile."""
    execution_id = _start(acme, member_only, shared_paths=["notes/todo.txt"])
    StorageFile.objects.create(
        org=acme, path=f"{OWN_FOLDER}concurrent.txt", name="concurrent.txt", item_type="file", size=4
    )
    StorageFile.objects.create(
        org=acme, path="notes/todo.txt", name="todo.txt", item_type="file", size=6
    )

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {f"{OWN_FOLDER}concurrent.txt": 4, "notes/todo.txt": 6}
    assert not TemporaryStorageAccount.objects.exists()


def test_a_failing_reconcile_does_not_stop_the_revocation(gateway, backend, acme, member_only):
    execution_id = _start(acme, member_only, shared_paths=["reports/"])
    _store(backend, acme, "reports/new.csv", 7)

    def failing_listing(prefix):
        raise ConnectionError("storage went away")

    backend.list_all_objects = failing_listing

    session_credential_service.revoke_for_test_run(execution_id)

    assert len(gateway.deleted) == 1
    assert not TemporaryStorageAccount.objects.exists()


def test_one_failing_granted_folder_does_not_skip_the_others(gateway, backend, acme, member_only):
    execution_id = _start(acme, member_only, shared_paths=["reports/"])
    _store(backend, acme, f"{OWN_FOLDER}kept.bin", 2)
    list_objects = backend.list_all_objects

    def failing_for_reports(prefix):
        if prefix.startswith("org_") and "reports" in prefix:
            raise ConnectionError("storage went away")
        return list_objects(prefix)

    backend.list_all_objects = failing_for_reports

    session_credential_service.revoke_for_test_run(execution_id)

    assert _indexed(acme) == {f"{OWN_FOLDER}kept.bin": 2}
    assert not TemporaryStorageAccount.objects.exists()


def test_an_account_without_recorded_folders_is_revoked_without_reconciling(
    gateway, backend, acme, member_only
):
    result = PythonCodeResult.objects.create(
        execution_id="exec-old", org_id=acme.id, status=PythonCodeResult.Status.COMPLETED
    )
    TemporaryStorageAccount.objects.create(
        python_code_result=result, access_key="issued-before-folders-were-recorded"
    )
    _store(backend, acme, "test-runs/anything.bin", 3)

    session_credential_service.revoke_for_test_run("exec-old")

    assert gateway.deleted == ["issued-before-folders-were-recorded"]
    assert _indexed(acme) == {}


def test_nested_grants_are_listed_once_under_their_outermost_folder_and_all_indexed(
    gateway, backend, acme
):
    result = PythonCodeResult.objects.create(
        execution_id="exec-nested", org_id=acme.id, status=PythonCodeResult.Status.COMPLETED
    )
    TemporaryStorageAccount.objects.create(
        python_code_result=result,
        access_key="nested-key",
        granted_folders=["a/b/", "a/", "a/z.txt", "c.txt", "d/"],
    )
    for path in ("a/b/x.bin", "a/z.txt", "c.txt", "d/y.bin", "e/outside.bin"):
        _store(backend, acme, path, 1)
    listed: list[str] = []
    list_all_objects = backend.list_all_objects

    def recording_listing(prefix):
        listed.append(prefix)
        return list_all_objects(prefix)

    backend.list_all_objects = recording_listing

    session_credential_service.revoke_for_test_run("exec-nested")

    assert listed == [f"org_{acme.id}/a/", f"org_{acme.id}/d/"]
    assert set(_indexed(acme)) == {"a/b/x.bin", "a/z.txt", "c.txt", "d/y.bin"}
    assert gateway.deleted == ["nested-key"]


def test_revoking_an_identity_first_indexes_what_its_runs_wrote(
    gateway, backend, acme, member_only
):
    _start(acme, member_only)
    _store(backend, acme, f"{OWN_FOLDER}unreported.bin", 9)

    session_credential_service.revoke_for_identity(org_id=acme.id, user_ids=[member_only.id])

    assert _indexed(acme) == {f"{OWN_FOLDER}unreported.bin": 9}
    assert not TemporaryStorageAccount.objects.exists()


def _bin_file(backend, org, path: str, size: int, days_ago: int) -> None:
    seed_file(backend, org.id, path, b"x" * size)
    batch = StorageManager(backend).delete(org.id, path, user=None)
    StorageFile.deleted_objects.filter(org=org, soft_delete_batch=batch).update(
        soft_deleted_at=timezone.now() - timedelta(days=days_ago)
    )


def _binned(org) -> set[str]:
    return set(StorageFile.deleted_objects.filter(org=org).values_list("path", flat=True))


def test_unreported_writes_that_leave_the_org_over_quota_purge_the_bin_for_an_admin_run(
    gateway, backend, acme, admin_acme, settings
):
    _bin_file(backend, acme, "oldest.bin", 10, days_ago=3)
    _bin_file(backend, acme, "newer.bin", 10, days_ago=2)
    execution_id = _start(acme, admin_acme)
    _store(backend, acme, f"{OWN_FOLDER}sneaky.bin", 15)
    settings.ORG_STORAGE_QUOTA = 30

    session_credential_service.revoke_for_test_run(execution_id)

    # 20 binned + 15 just indexed is 5 over: the oldest entry covers it.
    assert _binned(acme) == {"newer.bin"}
    assert _indexed(acme) == {f"{OWN_FOLDER}sneaky.bin": 15}
    assert not TemporaryStorageAccount.objects.exists()
    assert len(gateway.deleted) == 1


def test_the_bin_is_left_alone_at_the_end_of_a_run_that_may_not_purge(
    gateway, backend, acme, member_only, settings
):
    _bin_file(backend, acme, "old.bin", 10, days_ago=3)
    execution_id = _start(acme, member_only)
    _store(backend, acme, f"{OWN_FOLDER}sneaky.bin", 15)
    settings.ORG_STORAGE_QUOTA = 20

    session_credential_service.revoke_for_test_run(execution_id)

    assert _binned(acme) == {"old.bin"}
    assert len(gateway.deleted) == 1


def test_a_run_ending_inside_the_quota_purges_nothing(gateway, backend, acme, admin_acme, settings):
    _bin_file(backend, acme, "old.bin", 10, days_ago=3)
    execution_id = _start(acme, admin_acme)
    _store(backend, acme, f"{OWN_FOLDER}small.bin", 5)
    settings.ORG_STORAGE_QUOTA = 100

    session_credential_service.revoke_for_test_run(execution_id)

    assert _binned(acme) == {"old.bin"}
