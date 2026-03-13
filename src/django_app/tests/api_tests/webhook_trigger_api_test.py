import pytest
from django.urls import reverse

from tables.models.graph_models import Graph
from tables.models.webhook_models import WebhookTrigger


@pytest.mark.django_db
class TestWebhookTriggerAndNodeAPI:
    def test_create_webhook_trigger(self, api_client):
        """
        Basic smoke test for /api/webhook-triggers/ create endpoint.
        """
        url = reverse("webhooktrigger-list")
        payload = {
            "path": "myWebhook123",
            "ngrok_webhook_config": None,
        }

        response = api_client.post(url, payload, format="json")

        assert response.status_code == 201
        assert WebhookTrigger.objects.count() == 1
        trigger = WebhookTrigger.objects.first()
        assert trigger.path == "myWebhook123"
        assert trigger.ngrok_webhook_config is None

    def test_create_webhook_trigger_node_with_nested_trigger(self, api_client, graph: Graph):
        """
        Ensure /api/webhook-trigger-nodes/ accepts nested webhook_trigger payload
        and links node to the corresponding WebhookTrigger.
        """
        url = reverse("webhooktriggernode-list")

        payload = {
            "node_name": "My Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": ["requests"],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": {
                "path": "myWebhookNested",
                "ngrok_webhook_config": None,
            },
        }

        response = api_client.post(url, payload, format="json")

        assert response.status_code == 201
        data = response.json()
        assert data["node_name"] == "My Webhook Trigger"
        assert data["webhook_trigger"]["path"] == "myWebhookNested"

        # WebhookTrigger should be created or updated with this path
        trigger = WebhookTrigger.objects.get(path="myWebhookNested")
        assert trigger.ngrok_webhook_config is None

