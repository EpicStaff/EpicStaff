"""Changes the middleware's fallback could not name, because their URL carries no id,
recorded by layer-2 hooks with their target. Presentation tests: each goes through its
endpoint; only the object store is replaced, by the in-memory backend. The last tests call
the storage capture directly, for the failures no endpoint can provoke."""

from unittest.mock import patch

import pytest
from django.db import connection, transaction
from django.urls import reverse
from rest_framework import status

from tables.models import Graph, GraphStorageFile, GraphVersion, SourceCollection, StorageFile
from src.shared.models import UserAction
from tables.services.storage_service import db_sync
from tables.services.storage_service.db_sync import StorageFileSync
from tables.services.storage_service.manager import StorageManager
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

STORAGE_URL = "/api/storage/"


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


@pytest.fixture
def storage_manager():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=manager):
        yield manager


def _target(event) -> tuple:
    return event.action, event.target_type, event.target_id, event.target_name


def _only_event(sent_events):
    # One event, and from a hook: the fallback always sets a route.
    [event] = sent_events
    assert event.route is None
    return event


def _post(client, url, body, capture, expected_status=status.HTTP_200_OK):
    with capture(execute=True):
        response = client.post(url, body, format="json")
    assert response.status_code == expected_status, response.content
    return response


# ---- knowledge collections ----


def test_collection_create_records_created_with_its_name(
    admin_client, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    _post(
        admin_client,
        "/api/source-collections/",
        {"collection_name": "Contracts"},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    collection = SourceCollection.objects.get(org=acme, collection_name="Contracts")
    event = _only_event(sent_events)
    assert _target(event) == ("created", "knowledge collection", str(collection.pk), "Contracts")
    assert (event.org_id, event.actor_user_id) == (acme.id, admin_acme.id)


# ---- flow versions ----


def test_flow_version_create_records_created_under_its_flow(
    admin_client, acme, flow, sent_events, django_capture_on_commit_callbacks
):
    _post(
        admin_client,
        reverse("graph-versions-list"),
        {"graph_id": flow.id, "name": "Before refactor"},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    version = GraphVersion.objects.get(graph=flow)
    event = _only_event(sent_events)
    assert _target(event) == ("created", "flow version", str(version.pk), "Before refactor")
    assert (event.parent_type, event.parent_id, event.parent_name) == (
        "flow",
        str(flow.id),
        "Billing flow",
    )
    assert event.org_id == acme.id


def test_flow_version_of_another_orgs_flow_is_404_and_records_nothing(
    admin_client, beta, sent_events, django_capture_on_commit_callbacks
):
    other_org_flow = Graph.objects.create(name="Beta flow", org=beta)

    _post(
        admin_client,
        reverse("graph-versions-list"),
        {"graph_id": other_org_flow.id, "name": "Stolen"},
        django_capture_on_commit_callbacks,
        status.HTTP_404_NOT_FOUND,
    )

    assert not GraphVersion.objects.filter(graph=other_org_flow).exists()
    assert sent_events == []


# ---- storage ----


def test_storage_mkdir_records_the_folder_not_its_new_ancestors(
    admin_client, acme, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    _post(
        admin_client,
        f"{STORAGE_URL}mkdir/",
        {"path": "reports/2026"},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    folder = StorageFile.objects.get(org=acme, path="reports/2026/")
    assert StorageFile.objects.filter(org=acme, path="reports/").exists()
    assert _target(_only_event(sent_events)) == ("created", "storage folder", str(folder.id), "reports/2026/")


@pytest.mark.parametrize(
    "seeded_path, from_path, to_path, entry_path, entry_type, old_path",
    [
        ("docs/old.txt", "docs/old.txt", "docs/new.txt", "docs/new.txt", "storage file", "docs/old.txt"),
        ("docs/a.txt", "docs", "papers", "papers/", "storage folder", "docs/"),
    ],
    ids=["file", "folder"],
)
def test_storage_rename_records_renamed_with_the_old_path(
    seeded_path,
    from_path,
    to_path,
    entry_path,
    entry_type,
    old_path,
    admin_client,
    acme,
    storage_manager,
    sent_events,
    django_capture_on_commit_callbacks,
):
    seed_file(storage_manager._backend, acme.id, seeded_path, b"x")

    _post(
        admin_client,
        f"{STORAGE_URL}rename/",
        {"from_path": from_path, "to_path": to_path},
        django_capture_on_commit_callbacks,
    )

    entry = StorageFile.objects.get(org=acme, path=entry_path)
    event = _only_event(sent_events)
    assert _target(event) == ("renamed", entry_type, str(entry.id), entry_path)
    assert event.previous_name == old_path


def test_storage_move_records_moved_with_both_paths(
    admin_client, acme, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "a.txt", b"x")
    storage_manager.mkdir(acme.id, "archive")
    moved_row_id = StorageFile.objects.get(org=acme, path="a.txt").id

    _post(
        admin_client,
        f"{STORAGE_URL}move/",
        {"from_path": "a.txt", "to_path": "archive"},
        django_capture_on_commit_callbacks,
    )

    event = _only_event(sent_events)
    assert _target(event) == ("moved", "storage file", str(moved_row_id), "archive/a.txt")
    assert event.previous_name == "a.txt"


@pytest.mark.parametrize(
    "seeded_path, from_path, entry_path, entry_type, source_path",
    [
        ("a.txt", "a.txt", "archive/a.txt", "storage file", "a.txt"),
        ("docs/a.txt", "docs", "archive/docs/", "storage folder", "docs/"),
    ],
    ids=["file", "folder"],
)
def test_storage_copy_records_copied_naming_the_copy_and_its_source(
    seeded_path,
    from_path,
    entry_path,
    entry_type,
    source_path,
    admin_client,
    acme,
    storage_manager,
    sent_events,
    django_capture_on_commit_callbacks,
):
    seed_file(storage_manager._backend, acme.id, seeded_path, b"x")
    storage_manager.mkdir(acme.id, "archive")

    _post(
        admin_client,
        f"{STORAGE_URL}copy/",
        {"from_path": from_path, "to_path": "archive"},
        django_capture_on_commit_callbacks,
    )

    copy = StorageFile.objects.get(org=acme, path=entry_path)
    event = _only_event(sent_events)
    assert _target(event) == ("copied", entry_type, str(copy.id), entry_path)
    assert (event.org_id, event.previous_name) == (acme.id, source_path)


def _cross_org_transfer(client, transfer, acme, beta, capture):
    _post(
        client,
        f"{STORAGE_URL}{transfer}/",
        {
            "from_path": "a.txt",
            "to_path": "inbox",
            "source_org_id": acme.id,
            "destination_org_id": beta.id,
        },
        capture,
    )


def _carries_path(event, path) -> bool:
    return path in (event.target_name, event.previous_name, event.parent_name)


def test_storage_cross_org_copy_is_recorded_in_the_destination_org_only(
    superadmin_in_acme, acme, beta, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "a.txt", b"x")

    _cross_org_transfer(superadmin_in_acme, "copy", acme, beta, django_capture_on_commit_callbacks)

    landed = StorageFile.objects.get(org=beta, path="inbox/a.txt")
    event = _only_event(sent_events)
    assert _target(event) == ("copied", "storage file", str(landed.id), "inbox/a.txt")
    # The destination org never learns where in the source org the entry came from.
    assert (event.org_id, event.previous_name) == (beta.id, None)
    assert not _carries_path(event, "a.txt")


def test_storage_cross_org_move_is_recorded_in_both_orgs_naming_only_their_own_paths(
    superadmin_in_acme, acme, beta, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "a.txt", b"x")
    source_row_id = StorageFile.objects.get(org=acme, path="a.txt").id

    _cross_org_transfer(superadmin_in_acme, "move", acme, beta, django_capture_on_commit_callbacks)

    landed = StorageFile.objects.get(org=beta, path="inbox/a.txt")
    by_org = {event.org_id: event for event in sent_events}
    assert len(sent_events) == 2
    # Each org learns only its own side: what left, or what arrived.
    assert _target(by_org[acme.id]) == ("moved", "storage file", str(source_row_id), "a.txt")
    assert by_org[acme.id].previous_name is None
    assert not _carries_path(by_org[acme.id], "inbox/a.txt")
    assert _target(by_org[beta.id]) == ("moved", "storage file", str(landed.id), "inbox/a.txt")
    assert by_org[beta.id].previous_name is None
    assert not _carries_path(by_org[beta.id], "a.txt")


def test_storage_add_to_flow_records_the_flow_updated_once(
    admin_client, acme, flow, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "docs/a.txt", b"x")
    seed_file(storage_manager._backend, acme.id, "docs/b.txt", b"x")

    _post(
        admin_client,
        f"{STORAGE_URL}add-to-graph/",
        {"paths": ["docs/a.txt", "docs/b.txt"], "graph_ids": [flow.id]},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    assert GraphStorageFile.objects.filter(graph=flow).count() == 2
    event = _only_event(sent_events)
    assert _target(event) == ("updated", "flow", str(flow.id), "Billing flow")
    assert event.org_id == acme.id


def test_storage_add_to_flow_that_already_has_the_file_records_nothing(
    admin_client, acme, flow, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "docs/a.txt", b"x")
    body = {"paths": ["docs/a.txt"], "graph_ids": [flow.id]}
    _post(admin_client, f"{STORAGE_URL}add-to-graph/", body, django_capture_on_commit_callbacks, 201)
    sent_events.clear()

    _post(admin_client, f"{STORAGE_URL}add-to-graph/", body, django_capture_on_commit_callbacks, 201)

    assert sent_events == []


def test_storage_remove_from_flow_records_the_flow_updated_and_only_when_detached(
    admin_client, acme, flow, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "docs/a.txt", b"x")
    _post(
        admin_client,
        f"{STORAGE_URL}add-to-graph/",
        {"paths": ["docs/a.txt"], "graph_ids": [flow.id]},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )
    sent_events.clear()
    body = {"paths": ["docs/a.txt"], "graph_ids": [flow.id]}

    for _attempt in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.delete(f"{STORAGE_URL}remove-from-graph/", body, format="json")
        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

    # The second call detached nothing, so it adds no record, not even the fallback's.
    event = _only_event(sent_events)
    assert _target(event) == ("updated", "flow", str(flow.id), "Billing flow")


# ---- users created by a superadmin ----


def test_admin_user_create_into_an_org_records_created_user_in_that_org(
    client_as, superadmin, acme, sent_events, django_capture_on_commit_callbacks
):
    _post(
        client_as(superadmin),
        "/api/admin/users/",
        {"email": "new.hire@example.com", "password": "StrongPass123!", "organization_id": acme.id},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    new_user = superadmin.__class__.objects.get(email="new.hire@example.com")
    event = _only_event(sent_events)
    assert _target(event) == ("created", "user", str(new_user.pk), "new.hire@example.com")
    assert (event.org_id, event.actor_user_id) == (acme.id, superadmin.id)


def test_admin_user_create_with_no_org_records_nothing(
    client_as, superadmin, sent_events, django_capture_on_commit_callbacks
):
    _post(
        client_as(superadmin),
        "/api/admin/users/",
        {"email": "loner@example.com", "password": "StrongPass123!"},
        django_capture_on_commit_callbacks,
        status.HTTP_201_CREATED,
    )

    assert sent_events == []


# ---- storage capture runs after the object store committed, so it must never fail ----


def test_a_failing_storage_capture_never_raises_and_leaves_the_transaction_usable(
    acme, admin_acme, sent_events, django_capture_on_commit_callbacks, monkeypatch
):
    StorageFile.objects.create(org=acme, path="a.txt", name="a.txt", item_type="file")

    def failing_record(**kwargs):
        # Fails on the server, which aborts the transaction unless a savepoint contains it.
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(db_sync, "record_user_action", failing_record)

    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        StorageFileSync.record_transfer(UserAction.CREATED, acme.id, "a.txt", user=admin_acme)
        assert StorageFile.objects.filter(org=acme, path="a.txt").exists()

    assert sent_events == []


def test_storage_capture_reads_nothing_with_the_switch_off(
    acme, admin_acme, settings, django_assert_num_queries
):
    StorageFile.objects.create(org=acme, path="a.txt", name="a.txt", item_type="file")
    settings.USER_AUDIT_TRAIL_ENABLED = False

    with django_assert_num_queries(0):
        StorageFileSync.record_transfer(UserAction.CREATED, acme.id, "a.txt", user=admin_acme)
