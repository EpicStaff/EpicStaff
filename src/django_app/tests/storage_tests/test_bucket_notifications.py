"""The store's bucket notifications keep the file index, and so the quota, in step with what
run code writes straight to the store.

A notification names a key and nothing in it is believed: the object is read again from the
store. An organization the notified writes take over its quota loses every temporary storage
account at once, not when its runs end.

Through the internal endpoint the store calls; real services and database, in-memory storage
backend, fake storage admin API.
"""

from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote_plus

import pytest
from src.shared.models.storage_scope import StorageAction
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services import session_credential_service as service_module
from storage_credentials.services.session_credential_service import session_credential_service
from agents.models import AgentDefinition
from tables.models import Graph, PythonCodeResult, Session, StorageFile
from tables.models.realtime_models import RealtimeAgentChat, RealtimeAgentDefinition
from tables.services.storage_service import bucket_events
from tables.services.storage_service.quota import org_used_bytes

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import (
    GATEWAY_PATH,
    ORG_CREDENTIALS_PATH,
    FakeStorageGateway,
)
from tests.services_tests.test_storage_grant_accounts import _issue as issue_session_accounts
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db

URL = "/internal/storage-events/"
BUCKET = "bucket"
APP_KEY = "app-root-key"
RUN_KEY = "temp-access-1"
QUOTA = 100


@pytest.fixture(autouse=True)
def _storage_settings(settings):
    settings.STORAGE_BUCKET_NAME = BUCKET
    settings.STORAGE_ACCESS_KEY = APP_KEY
    settings.ORG_STORAGE_QUOTA = QUOTA


@pytest.fixture
def backend(monkeypatch):
    in_memory = InMemoryStorageBackend(organization_prefix="")
    for module in (bucket_events, service_module):
        monkeypatch.setattr(module, "get_storage_backend", lambda organization_prefix="": in_memory)
    return in_memory


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


def _record(key: str, *, event="s3:ObjectCreated:Put", principal=RUN_KEY, bucket=BUCKET) -> dict:
    # The store sends keys form-encoded: a space arrives as "+".
    return {
        "eventName": event,
        "userIdentity": {"principalId": principal},
        "s3": {"bucket": {"name": bucket}, "object": {"key": quote_plus(key, safe="/")}},
    }


def _notify(client, *records: dict):
    response = client.post(URL, {"Records": list(records)}, content_type="application/json")
    assert response.status_code == 204, response.content
    return response


def _store(backend, org, path: str, size: int) -> str:
    key = f"org_{org.id}/{path}"
    backend.put_bytes(key, b"x" * size)
    return key


def _indexed(org) -> dict[str, int | None]:
    return {row.path: row.size for row in StorageFile.objects.filter(org=org, item_type="file")}


def _start_test_run(org, execution_id: str) -> PythonCodeResult:
    result = PythonCodeResult.objects.create(
        execution_id=execution_id, org_id=org.id, status=PythonCodeResult.Status.PENDING
    )
    own_folder = f"test-runs/{execution_id}/"
    session_credential_service.issue_for_test_run(
        result,
        [own_folder, "reports/"],
        org.id,
        own_paths=[own_folder],
        shared_actions=frozenset(StorageAction),
    )
    return result


# --- Indexing -------------------------------------------------------------------------------


def test_an_object_run_code_wrote_is_indexed_at_its_stored_size(client, backend, acme):
    key = _store(backend, acme, "reports/out.csv", 42)

    _notify(client, _record(key))

    assert _indexed(acme) == {"reports/out.csv": 42}
    assert org_used_bytes(acme.id) == 42


def test_a_key_with_spaces_and_unicode_is_decoded_before_it_is_read(client, backend, acme):
    key = _store(backend, acme, "reports/звіт за рік.csv", 7)

    _notify(client, _record(key))

    assert _indexed(acme) == {"reports/звіт за рік.csv": 7}


@pytest.mark.parametrize(
    "path", ["reports/a\nb.txt", "reports/x\n"], ids=["embedded-newline", "trailing-newline"]
)
def test_a_key_with_a_newline_is_indexed_under_its_whole_path(client, backend, acme, path):
    key = f"org_{acme.id}/{path}"
    backend.put_raw_key(key, b"x" * 6)

    _notify(client, _record(key))

    assert _indexed(acme) == {path: 6}


def test_an_object_run_code_removed_drops_its_row(client, backend, acme):
    key = _store(backend, acme, "reports/out.csv", 42)
    _notify(client, _record(key))
    backend.delete_keys([key])

    _notify(client, _record(key, event="s3:ObjectRemoved:Delete"))

    assert _indexed(acme) == {}
    assert org_used_bytes(acme.id) == 0


def test_an_overwrite_updates_the_row_to_the_new_size(client, backend, acme):
    key = _store(backend, acme, "reports/out.csv", 42)
    _notify(client, _record(key))
    _store(backend, acme, "reports/out.csv", 9)

    _notify(client, _record(key))

    assert _indexed(acme) == {"reports/out.csv": 9}


def test_the_same_notification_twice_leaves_one_row(client, backend, acme):
    key = _store(backend, acme, "reports/out.csv", 42)

    _notify(client, _record(key), _record(key))
    _notify(client, _record(key))

    assert StorageFile.objects.filter(org=acme, path="reports/out.csv").count() == 1


@pytest.mark.parametrize(
    "event", ["s3:ObjectCreated:Put", "s3:ObjectRemoved:Delete"], ids=["created", "removed"]
)
def test_a_notification_is_checked_against_the_store_not_believed(client, backend, acme, event):
    """A forged or late record: a created object that is not stored gets no row, and a
    removed object that is still stored keeps its row."""
    stored_key = _store(backend, acme, "reports/kept.csv", 5)
    _notify(client, _record(stored_key))

    _notify(
        client,
        _record(f"org_{acme.id}/reports/never-stored.csv", event=event),
        _record(stored_key, event=event),
    )

    assert _indexed(acme) == {"reports/kept.csv": 5}


def test_a_late_creation_record_of_an_object_already_gone_keeps_its_row(client, backend, acme):
    """The app may be moving the file: it copied and deleted the object and is about to move
    the row. Only the removal record of the key drops the row."""
    StorageFile.objects.create(
        org=acme, path="reports/moving.csv", name="moving.csv", item_type="file", size=5
    )
    key = f"org_{acme.id}/reports/moving.csv"

    _notify(client, _record(key))
    assert _indexed(acme) == {"reports/moving.csv": 5}

    _notify(client, _record(key, event="s3:ObjectRemoved:Delete"))
    assert _indexed(acme) == {}


def test_a_write_by_the_app_s_own_storage_account_is_left_to_the_app(client, backend, acme):
    """The app indexes its own writes in the request; a rename's delete event reconciled in
    between would drop the row the app is about to move, with its flow attachments."""
    StorageFile.objects.create(org=acme, path="docs/a.txt", name="a.txt", item_type="file", size=3)
    removed_by_app = f"org_{acme.id}/docs/a.txt"
    written_by_app = _store(backend, acme, "docs/b.txt", 3)

    _notify(
        client,
        _record(removed_by_app, event="s3:ObjectRemoved:Delete", principal=APP_KEY),
        _record(written_by_app, principal=APP_KEY),
    )

    assert _indexed(acme) == {"docs/a.txt": 3}


@pytest.mark.parametrize(
    ("key", "bucket"),
    [
        ("org_{org}/reports/", BUCKET),
        ("org_{org}/.recycle-bin/1/old.csv", BUCKET),
        ("system/avatars/a.png", BUCKET),
        ("org_{org}/reports/out.csv", "another-bucket"),
    ],
    ids=["folder-marker", "recycle-bin", "outside-any-org", "another-bucket"],
)
def test_records_outside_an_organization_s_live_files_are_skipped(client, backend, acme, key, bucket):
    key = key.format(org=acme.id)
    backend.put_bytes(key, b"x" * 10)

    _notify(client, _record(key, bucket=bucket))

    assert not StorageFile.objects.filter(org=acme).exists()


def test_a_record_of_an_organization_that_no_longer_exists_changes_nothing(client, backend, acme):
    missing_org_id = acme.id + 10_000
    key = f"org_{missing_org_id}/reports/out.csv"
    backend.put_bytes(key, b"x" * 10)

    _notify(client, _record(key))

    assert not StorageFile.all_objects.filter(org_id=missing_org_id).exists()


# --- Objects the index cannot hold ----------------------------------------------------------


def test_an_executable_run_code_wrote_is_deleted_from_the_store(client, backend, acme):
    executable = _store(backend, acme, "reports/payload.sh", 10)
    neighbour = _store(backend, acme, "reports/data.txt", 5)

    _notify(client, _record(executable), _record(neighbour))

    assert not backend.exists(executable)
    assert _indexed(acme) == {"reports/data.txt": 5}


def test_a_key_with_a_backslash_is_deleted_and_the_key_it_normalizes_to_is_kept(
    client, backend, acme
):
    """Its row would be looked up under the normalized path, another object: the bytes would
    stay stored and uncounted."""
    normalized = _store(backend, acme, "reports/a/b.txt", 4)
    _notify(client, _record(normalized))
    backslashed = f"org_{acme.id}/reports/a\\b.txt"
    backend.put_raw_key(backslashed, b"x" * 50)

    _notify(client, _record(backslashed))

    assert not backend.has_raw_key(backslashed)
    assert backend.has_raw_key(normalized)
    assert _indexed(acme) == {"reports/a/b.txt": 4}


def _path_of_length(length: int) -> str:
    """A path of exactly `length` characters, in 200-character segments the store accepts."""
    return "/".join(["s" * 200] * 6)[:length]


@pytest.mark.parametrize(("length", "indexed"), [(1000, True), (1001, False)])
def test_a_path_longer_than_an_index_row_holds_is_deleted(client, backend, acme, length, indexed):
    """Writing its row would fail on every resend of the notification, and the bytes would
    stay uncounted."""
    path = _path_of_length(length)
    assert len(path) == length
    key = f"org_{acme.id}/{path}"
    backend.put_raw_key(key, b"x" * 3)

    _notify(client, _record(key))

    assert backend.has_raw_key(key) is indexed
    assert _indexed(acme) == ({path: 3} if indexed else {})


def test_a_removed_executable_or_backslash_key_deletes_nothing(client, backend, acme):
    executable = _store(backend, acme, "reports/payload.sh", 10)
    backslashed = f"org_{acme.id}/reports/a\\b.txt"
    backend.put_raw_key(backslashed, b"x" * 10)

    _notify(
        client,
        _record(executable, event="s3:ObjectRemoved:Delete"),
        _record(backslashed, event="s3:ObjectRemoved:Delete"),
    )

    assert backend.exists(executable)
    assert backend.has_raw_key(backslashed)


# --- Quota ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "revoked"),
    [(QUOTA, False), (QUOTA + 1, True)],
    ids=["exactly-at-quota", "one-byte-over"],
)
def test_writes_that_take_the_organization_over_its_quota_revoke_its_run_accounts(
    client, backend, gateway, acme, written, revoked
):
    _start_test_run(acme, "run-1")
    key = _store(backend, acme, "test-runs/run-1/big.bin", written)

    _notify(client, _record(key))

    assert org_used_bytes(acme.id) == written
    assert (gateway.deleted == [RUN_KEY]) is revoked
    assert TemporaryStorageAccount.objects.exists() is not revoked


def _start_session(org) -> None:
    session = Session.objects.create(
        graph=Graph.objects.create(org=org, name="flow"), status=Session.SessionStatus.PENDING
    )
    issue_session_accounts(session, org, [None])


def _start_realtime_chat(org) -> None:
    agent_definition = AgentDefinition.objects.create(org=org, name="voice")
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)
    )
    session_credential_service.issue_for_realtime_chat(
        realtime_agent_chat=chat, storage_allowed_paths=["reports/"], org_id=org.id
    )


def test_every_run_of_the_organization_is_cut_off_and_no_other_organization_s(
    client, backend, gateway, acme, beta
):
    _start_session(acme)  # temp-access-1
    _start_test_run(acme, "run-1")  # temp-access-2
    _start_realtime_chat(acme)  # temp-access-3
    _start_session(beta)  # temp-access-4
    _start_test_run(beta, "run-2")  # temp-access-5
    key = _store(backend, acme, "test-runs/run-1/big.bin", QUOTA + 1)

    _notify(client, _record(key))

    assert sorted(gateway.deleted) == ["temp-access-1", "temp-access-2", "temp-access-3"]
    assert sorted(TemporaryStorageAccount.objects.values_list("access_key", flat=True)) == [
        "temp-access-4",
        "temp-access-5",
    ]


def test_a_cut_off_run_is_revoked_before_its_folders_are_listed_and_what_it_wrote_is_counted(
    client, backend, gateway, acme
):
    """The cut-off waits for no listing, and the listing then sees everything the run wrote,
    a write whose notification was lost included."""
    _start_test_run(acme, "run-1")
    _store(backend, acme, "test-runs/run-1/unnotified.bin", 7)
    revoked_when_listed = []
    list_all_objects = backend.list_all_objects

    def listing(prefix):
        revoked_when_listed.append(list(gateway.deleted))
        return list_all_objects(prefix)

    backend.list_all_objects = listing
    key = _store(backend, acme, "test-runs/run-1/big.bin", QUOTA + 1)

    _notify(client, _record(key))

    assert revoked_when_listed and all(seen == [RUN_KEY] for seen in revoked_when_listed)
    assert _indexed(acme) == {"test-runs/run-1/unnotified.bin": 7, "test-runs/run-1/big.bin": QUOTA + 1}


def test_a_cut_off_run_s_incomplete_uploads_in_its_own_folder_are_aborted(
    client, backend, gateway, acme
):
    """The store does not say who started an upload: one in a shared folder may be the app's
    own, so it is left to the bucket's lifecycle rule."""
    _start_test_run(acme, "run-1")
    own = f"org_{acme.id}/test-runs/run-1/parked.bin"
    shared = f"org_{acme.id}/reports/parked.bin"
    backend.incomplete_uploads = [own, shared]
    key = _store(backend, acme, "test-runs/run-1/big.bin", QUOTA + 1)

    _notify(client, _record(key))

    assert backend.incomplete_uploads == [shared]


def test_a_run_whose_writes_were_counted_cannot_mint_again(client, backend, gateway, acme):
    from storage_credentials.exceptions import OrganizationStorageFullError

    key = _store(backend, acme, "reports/big.bin", QUOTA + 1)
    _notify(client, _record(key))

    with pytest.raises(OrganizationStorageFullError):
        _start_test_run(acme, "run-1")
    assert gateway.created == []


# --- The endpoint ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'"Records"'], ids=["not-json", "a-list", "a-string"]
)
def test_a_body_that_is_not_a_notification_is_a_400(client, body):
    response = client.post(URL, body, content_type="application/json")

    assert response.status_code == 400


def test_only_post_is_accepted(client):
    assert client.get(URL).status_code == 405


def test_a_notification_with_no_records_is_accepted(client):
    assert client.post(URL, {}, content_type="application/json").status_code == 204


def test_the_route_is_not_under_the_api_prefix(client):
    assert client.post(f"/api{URL}", {}, content_type="application/json").status_code == 404
