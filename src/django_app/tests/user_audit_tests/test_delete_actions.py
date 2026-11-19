from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import get_resolver, reverse
from django.utils import timezone
from rest_framework import status

from rbac.authorship import LastEditDestroyViewSetMixin
from rbac.models import Role
from tables.models import Edge, Graph, PythonCode, PythonNode, Secret, StorageFile
from tables.models.base_models import SoftDeleteMixin
from tables.services.graph_bulk_save_service.registry import (
    EDGE_DELETE_CONFIGS,
    NODE_TYPE_REGISTRY,
)
from tables.services.recycle_bin import empty_service
from tables.services.recycle_bin.purge_service import RETENTION_JOB_ACTOR, PurgeService
from tables.services.secrets import secret_service
from tables.services.soft_delete import DeleteService
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from user_audit.context import user_action_context

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

FLOWS_URL = "/api/graphs/"
STORAGE_URL = "/api/storage/"


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


def _python_node(flow, node_name) -> PythonNode:
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonNode.objects.create(graph=flow, python_code=python_code, node_name=node_name)


def _binned_flow(org, name) -> Graph:
    flow = Graph.objects.create(name=name, org=org)
    flow.delete()
    return flow


@pytest.fixture
def storage_manager():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=manager):
        yield manager


def _target(event) -> tuple:
    return event.action, event.target_type, event.target_id, event.target_name


def _parent(event) -> tuple:
    return event.parent_type, event.parent_id, event.parent_name


def _save_flow(client, flow, capture, **payload):
    flow.refresh_from_db()
    with capture(execute=True):
        response = client.post(
            reverse("graphs-save-flow", args=[flow.id]),
            {"save_version": flow.save_version, **payload},
            format="json",
        )
    assert response.status_code == status.HTTP_200_OK, response.content


def test_binning_a_flow_records_one_moved_to_recycle_bin_not_one_per_node(
    admin_client, flow, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    _python_node(flow, "Fetch invoices")
    _python_node(flow, "Send reminders")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{FLOWS_URL}{flow.id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    # One event, and no route: DeleteService recorded it, so the fallback stayed out.
    [event] = sent_events
    assert _target(event) == ("moved_to_recycle_bin", "flow", str(flow.id), "Billing flow")
    assert (event.org_id, event.actor_user_id, event.route) == (acme.id, admin_acme.id, None)


def test_delete_service_records_deleted_for_a_row_it_cannot_bin(
    rf, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    role = Role.objects.create(org=acme, name="Auditor")
    role_id = role.id
    request = rf.delete("/api/admin/roles/")
    request.user = admin_acme

    with user_action_context(request), django_capture_on_commit_callbacks(execute=True):
        DeleteService.delete(role)

    assert not Role.objects.filter(pk=role_id).exists()
    [event] = sent_events
    assert _target(event) == ("deleted", "role", str(role_id), "Auditor")


def test_deleting_an_already_binned_flow_records_nothing_and_keeps_the_fallback_out(
    rf, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    # A second delete that lost the race: the first one binned the flow and recorded it.
    flow = _binned_flow(acme, "Orders")
    request = rf.delete(f"{FLOWS_URL}{flow.id}/")
    request.user = admin_acme

    with user_action_context(request) as context, django_capture_on_commit_callbacks(
        execute=True
    ):
        assert flow.delete() is None

    assert sent_events == []
    assert context.recorded is True


def _subclasses(base: type) -> set[type]:
    direct = set(base.__subclasses__())
    return direct.union(*(_subclasses(subclass) for subclass in direct))


def _last_edit_destroy_models() -> set[type]:
    # Loading the URLconf imports every view module, so every viewset is a subclass by now.
    get_resolver().url_patterns
    return {viewset.queryset.model for viewset in _subclasses(LastEditDestroyViewSetMixin)}


@pytest.mark.parametrize(
    "deleted_model",
    sorted(
        _last_edit_destroy_models()
        | {config.model_class for config in [*EDGE_DELETE_CONFIGS, *NODE_TYPE_REGISTRY]},
        key=lambda model: model.__name__,
    ),
    ids=lambda model: model.__name__,
)
def test_rows_the_last_edit_tracker_records_as_deleted_are_never_binned(deleted_model):
    # The tracker records these deletes as "deleted". A recycle-bin root would be binned
    # by its REST delete and recorded again by DeleteService, and hard-deleted past the
    # bin by graph save's queryset delete.
    assert not issubclass(deleted_model, SoftDeleteMixin)


def test_bulk_delete_records_each_picked_flow(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    flows = [Graph.objects.create(name=name, org=acme) for name in ("Orders", "Refunds")]

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            f"{FLOWS_URL}bulk-delete/", {"ids": [flow.id for flow in flows]}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sorted(_target(event) for event in sent_events) == [
        ("moved_to_recycle_bin", "flow", str(flows[0].id), "Orders"),
        ("moved_to_recycle_bin", "flow", str(flows[1].id), "Refunds"),
    ]


def test_restore_records_restored(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    flow = _binned_flow(acme, "Orders")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(f"{FLOWS_URL}{flow.id}/restore/")

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert _target(event) == ("restored", "flow", str(flow.id), "Orders")
    assert event.org_id == acme.id


def test_bulk_restore_records_each_item(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    flows = [_binned_flow(acme, name) for name in ("Orders", "Refunds")]

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            f"{FLOWS_URL}recycle-bin/restore/", {"ids": [flow.id for flow in flows]}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sorted(_target(event) for event in sent_events) == [
        ("restored", "flow", str(flows[0].id), "Orders"),
        ("restored", "flow", str(flows[1].id), "Refunds"),
    ]


def test_purge_from_the_recycle_bin_records_deleted(
    superadmin_in_acme, acme, superadmin, sent_events, django_capture_on_commit_callbacks
):
    flow = _binned_flow(acme, "Orders")

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_in_acme.delete(f"{FLOWS_URL}{flow.id}/purge/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    [event] = sent_events
    assert _target(event) == ("deleted", "flow", str(flow.id), "Orders")
    assert (event.org_id, event.actor_user_id) == (acme.id, superadmin.id)


def test_purge_expired_records_nothing(
    rf, acme, settings, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    settings.RECYCLE_BIN_RETENTION_DAYS = 7
    flow = _binned_flow(acme, "Orders")
    Graph.all_objects.filter(pk=flow.pk).update(
        soft_deleted_at=timezone.now() - timedelta(days=8)
    )
    request = rf.post("/api/recycle-bin/purge/")
    request.user = admin_acme

    with user_action_context(request), django_capture_on_commit_callbacks(execute=True):
        PurgeService.purge_expired()

    assert not Graph.all_objects.filter(pk=flow.pk).exists()
    assert sent_events == []


def test_empty_bin_records_one_per_item(
    superadmin_in_acme, acme, monkeypatch, sent_events, django_capture_on_commit_callbacks
):
    flow = _binned_flow(acme, "Orders")
    _python_node(Graph.all_objects.get(pk=flow.pk), "Fetch invoices")
    secret = secret_service.create(text="value-for-tests-only", org=acme, name="api-key")
    secret.delete()
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    monkeypatch.setattr(empty_service, "get_storage_manager", lambda: manager)
    seed_file(manager._backend, acme.id, "reports/march.pdf", b"pdf")
    manager.delete(acme.id, "reports/march.pdf", user=None)
    binned_file = StorageFile.all_objects.get(org=acme, path="reports/march.pdf")

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_in_acme.post("/api/recycle-bin/empty/")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not Secret.all_objects.filter(pk=secret.pk).exists()
    assert sorted(_target(event) for event in sent_events) == sorted(
        [
            ("deleted", "flow", str(flow.id), "Orders"),
            ("deleted", "secret", str(secret.id), "api-key"),
            ("deleted", "storage file", str(binned_file.id), "reports/march.pdf"),
        ]
    )
    assert {event.org_id for event in sent_events} == {acme.id}


def test_graph_save_deleting_node_records_deleted_node_in_flow(
    admin_client, flow, acme, sent_events, django_capture_on_commit_callbacks
):
    node = _python_node(flow, "Fetch invoices")
    _python_node(flow, "Send reminders")

    _save_flow(
        admin_client,
        flow,
        django_capture_on_commit_callbacks,
        deleted={"python_node_ids": [node.id]},
    )

    # Gone for good, not binned: so "deleted" is what happened.
    assert not PythonNode.all_objects.filter(pk=node.pk).exists()
    [event] = sent_events
    assert _target(event) == ("deleted", "python code node", str(node.id), "Fetch invoices")
    assert _parent(event) == ("flow", str(flow.id), "Billing flow")
    assert event.org_id == acme.id


def test_graph_save_deleting_only_edges_records_updated_flow(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    first, second, third = (_python_node(flow, name) for name in ("One", "Two", "Three"))
    edges = [
        Edge.objects.create(graph=flow, start_node_id=first.id, end_node_id=second.id),
        Edge.objects.create(graph=flow, start_node_id=second.id, end_node_id=third.id),
    ]

    _save_flow(
        admin_client,
        flow,
        django_capture_on_commit_callbacks,
        deleted={"edge_ids": [edge.id for edge in edges]},
    )

    assert not Edge.objects.filter(graph=flow).exists()
    [event] = sent_events
    assert _target(event) == ("updated", "flow", str(flow.id), "Billing flow")
    assert _parent(event) == (None, None, None)


def test_rest_node_delete_records_deleted_node_in_flow(
    admin_client, flow, acme, sent_events, django_capture_on_commit_callbacks
):
    node = _python_node(flow, "Fetch invoices")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(reverse("pythonnode-detail", args=[node.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not PythonNode.all_objects.filter(pk=node.pk).exists()
    [event] = sent_events
    assert _target(event) == ("deleted", "python code node", str(node.id), "Fetch invoices")
    assert _parent(event) == ("flow", str(flow.id), "Billing flow")
    assert event.org_id == acme.id


def test_rest_edge_delete_records_updated_flow(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    first, second = (_python_node(flow, name) for name in ("One", "Two"))
    edge = Edge.objects.create(graph=flow, start_node_id=first.id, end_node_id=second.id)

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(reverse("edge-detail", args=[edge.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    [event] = sent_events
    assert _target(event) == ("updated", "flow", str(flow.id), "Billing flow")


def _delete_storage_paths(client, paths, capture):
    with capture(execute=True):
        response = client.delete(f"{STORAGE_URL}delete/", {"paths": paths}, format="json")
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


def test_storage_file_delete_records_moved_to_recycle_bin(
    admin_client, acme, admin_acme, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "reports/march.pdf", b"pdf")

    _delete_storage_paths(admin_client, ["reports/march.pdf"], django_capture_on_commit_callbacks)

    binned = StorageFile.deleted_objects.get(org=acme, path="reports/march.pdf")
    [event] = sent_events
    assert _target(event) == ("moved_to_recycle_bin", "storage file", str(binned.id), "reports/march.pdf")
    assert (event.org_id, event.actor_user_id) == (acme.id, admin_acme.id)


def test_storage_folder_delete_records_one_not_per_file(
    admin_client, acme, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    storage_manager.mkdir(acme.id, "reports", user=None)
    seed_file(storage_manager._backend, acme.id, "reports/march.pdf", b"pdf")
    seed_file(storage_manager._backend, acme.id, "reports/april.pdf", b"pdf")

    _delete_storage_paths(admin_client, ["reports"], django_capture_on_commit_callbacks)

    folder = StorageFile.deleted_objects.get(org=acme, path="reports/")
    [event] = sent_events
    assert _target(event) == ("moved_to_recycle_bin", "storage folder", str(folder.id), "reports/")


def test_storage_restore_records_restored(
    admin_client, acme, storage_manager, sent_events, django_capture_on_commit_callbacks
):
    seed_file(storage_manager._backend, acme.id, "reports/march.pdf", b"pdf")
    storage_manager.delete(acme.id, "reports/march.pdf", user=None)
    binned = StorageFile.deleted_objects.get(org=acme, path="reports/march.pdf")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            f"{STORAGE_URL}recycle-bin/restore/", {"ids": [binned.id]}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert _target(event) == ("restored", "storage file", str(binned.id), "reports/march.pdf")
    assert event.org_id == acme.id


def test_storage_purge_by_retention_job_records_nothing(
    rf, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    seed_file(manager._backend, acme.id, "reports/march.pdf", b"pdf")
    manager.delete(acme.id, "reports/march.pdf", user=None)
    binned = StorageFile.deleted_objects.get(org=acme, path="reports/march.pdf")
    request = rf.post("/api/storage/recycle-bin/purge/")
    request.user = admin_acme

    with user_action_context(request), django_capture_on_commit_callbacks(execute=True):
        StorageRecycleBinService(manager).purge(acme.id, binned.id, actor=RETENTION_JOB_ACTOR)

    assert not StorageFile.all_objects.filter(pk=binned.pk).exists()
    assert sent_events == []


# ---- a capture that fails never fails the delete it describes ----


@pytest.fixture
def failing_describe(monkeypatch, sent_events):
    from user_audit import recorder

    def describe(instance):
        raise RuntimeError("describe failed")

    monkeypatch.setattr(recorder, "describe", describe)


@pytest.mark.usefixtures("failing_describe")
def test_binning_a_flow_succeeds_when_describing_it_fails(
    admin_client, flow, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{FLOWS_URL}{flow.id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not Graph.objects.filter(pk=flow.pk).exists()


@pytest.mark.usefixtures("failing_describe")
def test_a_rest_node_delete_succeeds_when_describing_it_fails(
    admin_client, flow, django_capture_on_commit_callbacks
):
    node = _python_node(flow, "Fetch invoices")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(reverse("pythonnode-detail", args=[node.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not PythonNode.all_objects.filter(pk=node.pk).exists()


@pytest.mark.usefixtures("failing_describe")
def test_a_purge_succeeds_when_describing_it_fails(
    superadmin_in_acme, acme, django_capture_on_commit_callbacks
):
    flow = _binned_flow(acme, "Orders")

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_in_acme.delete(f"{FLOWS_URL}{flow.id}/purge/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not Graph.all_objects.filter(pk=flow.pk).exists()
