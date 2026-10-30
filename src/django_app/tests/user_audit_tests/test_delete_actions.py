from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import Edge, Graph, PythonCode, PythonNode, Secret, StorageFile
from tables.services.recycle_bin import empty_service
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.secrets import secret_service
from tables.services.storage_service.manager import StorageManager
from user_audit.context import user_action_context

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

FLOWS_URL = "/api/graphs/"


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


def test_binning_a_flow_records_one_deleted_not_one_per_node(
    admin_client, flow, acme, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    _python_node(flow, "Fetch invoices")
    _python_node(flow, "Send reminders")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{FLOWS_URL}{flow.id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    [event] = sent_events
    assert _target(event) == ("deleted", "flow", str(flow.id), "Billing flow")
    assert (event.org_id, event.actor_user_id) == (acme.id, admin_acme.id)


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
        ("deleted", "flow", str(flows[0].id), "Orders"),
        ("deleted", "flow", str(flows[1].id), "Refunds"),
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


def test_purge_records_permanently_deleted(
    superadmin_in_acme, acme, superadmin, sent_events, django_capture_on_commit_callbacks
):
    flow = _binned_flow(acme, "Orders")

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_in_acme.delete(f"{FLOWS_URL}{flow.id}/purge/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    [event] = sent_events
    assert _target(event) == ("permanently_deleted", "flow", str(flow.id), "Orders")
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
            ("permanently_deleted", "flow", str(flow.id), "Orders"),
            ("permanently_deleted", "secret", str(secret.id), "api-key"),
            ("permanently_deleted", "storage file", str(binned_file.id), "march.pdf"),
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

    assert not PythonNode.objects.filter(pk=node.pk).exists()
    [event] = sent_events
    assert _target(event) == ("deleted", "python node", str(node.id), "Fetch invoices")
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
    [event] = sent_events
    assert _target(event) == ("deleted", "python node", str(node.id), "Fetch invoices")
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
