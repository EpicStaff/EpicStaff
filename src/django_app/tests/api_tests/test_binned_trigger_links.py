"""A trigger node keeps its link to a webhook trigger in the recycle bin: saving the
flow keeps it, a new link to a binned trigger is refused, and a restore reconnects."""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode, WebhookTriggerNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

REGISTER = "tables.signals.webhook_signals.WebhookTriggerService.register_webhooks"
PYTHON_CODE_DATA = {"code": "def main(**kwargs): ...", "entrypoint": "main", "libraries": []}


@pytest.fixture(autouse=True)
def _no_tunnel_calls():
    with patch(REGISTER, return_value=True):
        yield


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def graph(acme):
    return Graph.objects.create(name="Orders flow", org=acme)


def _binned_trigger(org, path):
    trigger = WebhookTrigger.objects.create(org=org, path=path, provider_type="ngrok")
    trigger.delete()
    return WebhookTrigger.all_objects.get(pk=trigger.pk)


def _webhook_node(graph, trigger):
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        webhook_trigger=trigger,
    )


def _webhook_entry(graph, node=None, trigger_id=None):
    entry = {
        "graph": graph.id,
        "node_name": "Hook",
        "metadata": {},
        "python_code": PYTHON_CODE_DATA,
        "webhook_trigger": trigger_id,
    }
    if node is not None:
        entry["id"] = node.id
    return entry


def _save(client, graph, list_key, entry):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, list_key: [entry]},
        format="json",
    )


def _trigger_error(response, list_key):
    return str(response.data["errors"][list_key][0]["errors"]["webhook_trigger"])


def test_saving_a_webhook_node_keeps_its_binned_trigger(acme_client, acme, graph):
    trigger = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    node = _webhook_node(graph, trigger)
    trigger.delete()

    response = _save(
        acme_client, graph, "webhook_trigger_node_list", _webhook_entry(graph, node, trigger.id)
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.webhook_trigger_id == trigger.id


def test_saving_a_telegram_node_keeps_its_binned_trigger(
    acme_client, acme, graph, mock_telegram_service
):
    trigger = WebhookTrigger.objects.create(org=acme, path="bot", provider_type="ngrok")
    node = TelegramTriggerNode.objects.create(graph=graph, node_name="Bot", webhook_trigger=trigger)
    trigger.delete()
    entry = {
        "id": node.id,
        "graph": graph.id,
        "node_name": "Bot",
        "metadata": {},
        "fields": [],
        "webhook_trigger": trigger.id,
    }

    response = _save(acme_client, graph, "telegram_trigger_node_list", entry)

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.webhook_trigger_id == trigger.id


def test_updating_a_node_through_its_endpoint_keeps_its_binned_trigger(acme_client, acme, graph):
    trigger = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    node = _webhook_node(graph, trigger)
    trigger.delete()

    response = acme_client.put(
        f"/api/webhook-trigger-nodes/{node.id}/",
        {**_webhook_entry(graph, trigger_id=trigger.id), "node_name": "Renamed hook"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert (node.node_name, node.webhook_trigger_id) == ("Renamed hook", trigger.id)


def test_a_new_node_cant_link_a_binned_trigger(acme_client, acme, graph):
    trigger = _binned_trigger(acme, "orders")

    response = _save(
        acme_client, graph, "webhook_trigger_node_list", _webhook_entry(graph, trigger_id=trigger.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "Invalid pk" in _trigger_error(response, "webhook_trigger_node_list")


def test_switching_to_another_binned_trigger_is_rejected(acme_client, acme, graph):
    current = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    node = _webhook_node(graph, current)
    other = _binned_trigger(acme, "refunds")

    response = _save(
        acme_client, graph, "webhook_trigger_node_list", _webhook_entry(graph, node, other.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "Invalid pk" in _trigger_error(response, "webhook_trigger_node_list")
    node.refresh_from_db()
    assert node.webhook_trigger_id == current.id


def test_a_binned_trigger_of_another_org_is_rejected(acme_client, beta, graph):
    theirs = _binned_trigger(beta, "theirs")

    response = _save(
        acme_client, graph, "webhook_trigger_node_list", _webhook_entry(graph, trigger_id=theirs.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "Invalid pk" in _trigger_error(response, "webhook_trigger_node_list")


def test_restoring_the_trigger_after_a_save_reconnects_the_node(acme_client, acme, graph):
    trigger = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    node = _webhook_node(graph, trigger)
    trigger.delete()
    saved = _save(
        acme_client, graph, "webhook_trigger_node_list", _webhook_entry(graph, node, trigger.id)
    )
    assert saved.status_code == status.HTTP_200_OK, saved.content

    response = acme_client.post(f"/api/webhook-triggers/{trigger.id}/restore/")

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.webhook_trigger_id == trigger.id
    assert node.webhook_trigger.active
