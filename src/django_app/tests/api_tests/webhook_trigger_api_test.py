import pytest
from django.urls import reverse

from tables.models.graph_models import Graph
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer


@pytest.mark.django_db
class TestWebhookTriggerAndNodeAPI:
    def test_create_webhook_trigger(self, auth_client):
        """
        Basic smoke test for /api/webhook-triggers/ create endpoint.
        Creates a trigger with no provider (provider_type=None).
        """
        url = reverse("webhooktrigger-list")
        payload = {
            "path": "myWebhook123",
            "provider_type": None,
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201
        assert WebhookTrigger.objects.count() == 1
        trigger = WebhookTrigger.objects.first()
        assert trigger.path == "myWebhook123"
        assert trigger.provider_type is None

    def test_create_webhook_trigger_node_with_nested_trigger(
        self, auth_client, graph: Graph
    ):
        """
        Ensure /api/webhook-trigger-nodes/ accepts nested webhook_trigger payload
        with no provider and links node to the corresponding WebhookTrigger.
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
                "provider_type": None,
            },
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201
        data = response.json()
        assert data["node_name"] == "My Webhook Trigger"
        assert data["webhook_trigger"]["path"] == "myWebhookNested"

        # WebhookTrigger should be created with no provider type
        trigger = WebhookTrigger.objects.get(path="myWebhookNested")
        assert trigger.provider_type is None

    def test_create_webhook_trigger_node_with_ngrok_trigger(
        self, auth_client, graph: Graph
    ):
        """
        Ensure /api/webhook-trigger-nodes/ accepts a nested ngrok webhook_trigger
        and creates both the WebhookTrigger and the linked NgrokWebhookConfig.
        """
        url = reverse("webhooktriggernode-list")

        payload = {
            "node_name": "My Ngrok Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": {
                "path": "myNgrokWebhook",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "test-ngrok",
                    "auth_token": "test-token-abc",
                    "domain": None,
                },
            },
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201
        data = response.json()
        assert data["node_name"] == "My Ngrok Webhook Trigger"
        assert data["webhook_trigger"]["path"] == "myNgrokWebhook"

        trigger = WebhookTrigger.objects.get(path="myNgrokWebhook")
        assert trigger.provider_type == ProviderType.NGROK
        assert NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_create_webhook_trigger_node_with_localhost_trigger(
        self, auth_client, graph: Graph
    ):
        """
        Ensure /api/webhook-trigger-nodes/ accepts a nested localhost webhook_trigger
        and creates both the WebhookTrigger and the linked LocalhostWebhookConfig.
        """
        url = reverse("webhooktriggernode-list")

        payload = {
            "node_name": "My Localhost Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": {
                "path": "myLocalhostWebhook",
                "provider_type": "localhost",
                "localhost_config": {
                    "name": "test-localhost",
                    "domain": "localhost:8080",
                },
            },
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201
        data = response.json()
        assert data["node_name"] == "My Localhost Webhook Trigger"
        assert data["webhook_trigger"]["path"] == "myLocalhostWebhook"

        trigger = WebhookTrigger.objects.get(path="myLocalhostWebhook")
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()


@pytest.mark.django_db
class TestWebhookTriggerProviderSwitchCleanup:
    """Cover WebhookTriggerNestedSerializer.update — switching provider_type
    must delete the orphan config from the previous provider in both
    directions, and when the provider is cleared entirely."""

    def _update(self, instance, data):
        serializer = WebhookTriggerNestedSerializer()
        return serializer.update(instance, data)

    def test_switch_ngrok_to_localhost_deletes_ngrok_config(self):
        trigger = WebhookTrigger.objects.create(
            path="switchNgrokToLocal", provider_type=ProviderType.NGROK
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="tok")

        self._update(
            trigger,
            {
                "provider_type": ProviderType.LOCALHOST,
                "localhost_config": {"name": "lh", "domain": "localhost:8080"},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()
        assert not NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_switch_localhost_to_ngrok_deletes_localhost_config(self):
        trigger = WebhookTrigger.objects.create(
            path="switchLocalToNgrok", provider_type=ProviderType.LOCALHOST
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="lh", domain="localhost:8080"
        )

        self._update(
            trigger,
            {
                "provider_type": ProviderType.NGROK,
                "ngrok_config": {"name": "ng", "auth_token": "tok", "domain": None},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.NGROK
        assert NgrokWebhookConfig.objects.filter(trigger=trigger).exists()
        assert not LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_update_deletes_orphan_independent_of_new_config_presence(self):
        """Internal `update()` contract: cleanup of the old provider's config
        must not depend on the new provider's config being supplied.

        Note: via the API, `validate()` rejects provider=ngrok/localhost
        without the matching config, so this exact payload can't reach the
        endpoint — but the cleanup must not be coupled to config presence
        (the original bug nested deletion inside the `and X_data` branch).
        The real API-reachable case of this class of bug is covered by
        `test_clear_provider_deletes_existing_config`."""
        trigger = WebhookTrigger.objects.create(
            path="switchNoData", provider_type=ProviderType.NGROK
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="tok")

        self._update(trigger, {"provider_type": ProviderType.LOCALHOST})

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert not NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_clear_provider_deletes_existing_config(self):
        trigger = WebhookTrigger.objects.create(
            path="clearProvider", provider_type=ProviderType.LOCALHOST
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="lh", domain="localhost:8080"
        )

        self._update(trigger, {"provider_type": None})

        trigger.refresh_from_db()
        assert trigger.provider_type is None
        assert not LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_no_provider_change_keeps_config(self):
        """Same provider + new config data updates in place, no deletion."""
        trigger = WebhookTrigger.objects.create(
            path="sameProvider", provider_type=ProviderType.NGROK
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="old")

        self._update(
            trigger,
            {
                "provider_type": ProviderType.NGROK,
                "ngrok_config": {"name": "ng", "auth_token": "new", "domain": None},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.NGROK
        cfg = NgrokWebhookConfig.objects.get(trigger=trigger)
        assert cfg.auth_token == "new"
