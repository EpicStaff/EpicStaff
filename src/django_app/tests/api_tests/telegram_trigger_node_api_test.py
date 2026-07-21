import pytest
from django.urls import reverse
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import WebhookTrigger


@pytest.mark.django_db
class TestTelegramTriggerViewSet:
    def test_create_telegram_trigger_node(
        self, auth_client, graph, mock_telegram_service
    ):
        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "StartNode",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "user_id",
                    "variable_path": "from.id",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201
        assert TelegramTriggerNode.objects.count() == 1
        assert TelegramTriggerNode.objects.first().fields.count() == 1
        # Verify signal triggered the service at least once
        assert mock_telegram_service.call_count >= 1

    def test_update_telegram_trigger_node(self, auth_client, graph, mocker):
        # 1. Mock the specific method on the Singleton class
        # This prevents the real network call during .create() and .put()
        mock_register = mocker.patch.object(
            TelegramTriggerService,
            "register_telegram_trigger",
            return_value={"ok": True},
        )

        # 2. Create the initial node (triggers signal -> uses mock)
        node = TelegramTriggerNode.objects.create(
            node_name="OldName",
            telegram_bot_api_key="12345:fake_key",
            graph=graph,
        )

        # 3. Update via API
        url = reverse("telegramtriggernode-detail", args=[node.id])
        data = {
            "node_name": "NewName",
            "telegram_bot_api_key": "54321:new_fake_key",
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "message.text",
                }
            ],
        }

        response = auth_client.put(url, data, format="json")

        # Assertions
        assert response.status_code == 200
        node.refresh_from_db()
        assert node.node_name == "NewName"
        assert node.telegram_bot_api_key == "54321:new_fake_key"

        # Verify the mock was called (once for create, once for update)
        assert mock_register.call_count == 2

    def test_create_telegram_trigger_node_with_webhook_trigger(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        EST-2987/EST-3491: inline trigger creation was removed — the
        telegram-trigger-nodes endpoint only accepts an *existing*
        WebhookTrigger id and links the node to it.
        """
        trigger = WebhookTrigger.objects.create(
            path="tgWebhook123", provider_type=None, org=default_org
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramWithWebhook",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "variables.telegram_data.user_input",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201, response.json()
        node = TelegramTriggerNode.objects.get(node_name="TelegramWithWebhook")
        assert node.webhook_trigger == trigger
        # Write side (POST response) still returns the plain id, unchanged.
        assert response.json()["webhook_trigger"] == trigger.id
        # service should still be called (signal)
        mock_telegram_service.assert_called()

    def test_get_telegram_trigger_node_expands_nested_trigger_info(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        GET on /api/telegram-trigger-nodes/{id}/ (and the list endpoint) must
        expand `webhook_trigger` to its full nested representation, not just
        the bare id — write side (POST/PATCH) is unaffected.
        """
        from tables.models.webhook_models import LocalhostWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tgWebhookForGet",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="tg-localhost", domain="localhost:9000"
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramGetNested",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [],
        }
        create_response = auth_client.post(url, data, format="json")
        assert create_response.status_code == 201, create_response.json()
        assert create_response.json()["webhook_trigger"] == trigger.id
        node_id = create_response.json()["id"]

        detail = auth_client.get(
            reverse("telegramtriggernode-detail", args=[node_id])
        )
        assert detail.status_code == 200, detail.json()
        wt = detail.json()["webhook_trigger"]
        assert wt is not None
        assert wt["id"] == trigger.id
        assert wt["path"] == "tgWebhookForGet"
        assert wt["provider_type"] == "localhost"
        assert wt["localhost_config"]["name"] == "tg-localhost"

        listing = auth_client.get(reverse("telegramtriggernode-list"))
        assert listing.status_code == 200
        listed = next(
            row for row in listing.json()["results"] if row["id"] == node_id
        )
        assert listed["webhook_trigger"]["path"] == "tgWebhookForGet"
